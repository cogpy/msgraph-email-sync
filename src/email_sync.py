#!/usr/bin/env python3
"""
Microsoft Graph Email Sync - Syncs emails from MS Graph to Neon PostgreSQL.
Uses application permissions from Entra AD Zone app (653 permissions).
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
import requests
import psycopg2
from psycopg2.extras import execute_values, Json

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class MSGraphClient:
    """Microsoft Graph API client using application permissions."""
    
    def __init__(self):
        self.tenant_id = os.environ.get("AZURE_TENANT_ID")
        self.client_id = os.environ.get("AZURE_CLIENT_ID")
        self.client_secret = os.environ.get("AZURE_CLIENT_SECRET")
        self.base_url = "https://graph.microsoft.com/v1.0"
        self.token = None
        self.token_expiry = None
    
    def _get_token(self) -> str:
        """Get or refresh access token."""
        if self.token and self.token_expiry and datetime.now() < self.token_expiry:
            return self.token
        
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        
        response = requests.post(url, data=data)
        response.raise_for_status()
        token_data = response.json()
        
        self.token = token_data["access_token"]
        self.token_expiry = datetime.now() + timedelta(seconds=token_data.get("expires_in", 3600) - 60)
        
        return self.token
    
    @property
    def headers(self) -> Dict[str, str]:
        """Get request headers with auth token."""
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json"
        }
    
    def get_users(self, select: str = "id,displayName,userPrincipalName,mail") -> List[Dict]:
        """Get all users in the tenant."""
        users = []
        url = f"{self.base_url}/users?$select={select}&$top=100"
        
        while url:
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()
            users.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        
        return users
    
    def get_user_messages(
        self,
        user_id: str,
        folder: str = "inbox",
        top: int = 100,
        skip: int = 0,
        since: Optional[datetime] = None,
        select: str = None
    ) -> List[Dict]:
        """Get messages for a specific user."""
        if select is None:
            select = (
                "id,conversationId,subject,bodyPreview,body,from,toRecipients,"
                "ccRecipients,bccRecipients,receivedDateTime,sentDateTime,"
                "hasAttachments,importance,isRead,isDraft,webLink,categories,"
                "parentFolderId"
            )
        
        url = f"{self.base_url}/users/{user_id}/mailFolders/{folder}/messages"
        params = {
            "$select": select,
            "$top": top,
            "$skip": skip,
            "$orderby": "receivedDateTime desc"
        }
        
        if since:
            params["$filter"] = f"receivedDateTime ge {since.isoformat()}Z"
        
        messages = []
        full_url = f"{url}?{'&'.join(f'{k}={v}' for k, v in params.items())}"
        
        while full_url and len(messages) < 1000:  # Limit to 1000 per sync
            response = requests.get(full_url, headers=self.headers)
            if response.status_code == 404:
                logger.warning(f"Folder {folder} not found for user {user_id}")
                break
            response.raise_for_status()
            data = response.json()
            messages.extend(data.get("value", []))
            full_url = data.get("@odata.nextLink")
        
        return messages
    
    def get_message_attachments(self, user_id: str, message_id: str) -> List[Dict]:
        """Get attachments for a specific message."""
        url = f"{self.base_url}/users/{user_id}/messages/{message_id}/attachments"
        
        response = requests.get(url, headers=self.headers)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        
        return response.json().get("value", [])
    
    def get_mail_folders(self, user_id: str) -> List[Dict]:
        """Get mail folders for a user."""
        url = f"{self.base_url}/users/{user_id}/mailFolders?$top=100"
        
        folders = []
        while url:
            response = requests.get(url, headers=self.headers)
            if response.status_code == 404:
                return []
            response.raise_for_status()
            data = response.json()
            folders.extend(data.get("value", []))
            url = data.get("@odata.nextLink")
        
        return folders


class NeonDB:
    """Neon PostgreSQL database client."""
    
    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.environ.get("DATABASE_URL")
        self.conn = None
    
    def connect(self):
        """Establish database connection."""
        if not self.conn or self.conn.closed:
            self.conn = psycopg2.connect(self.connection_string)
        return self.conn
    
    def close(self):
        """Close database connection."""
        if self.conn and not self.conn.closed:
            self.conn.close()
    
    def upsert_account(self, user_id: str, upn: str, display_name: str) -> int:
        """Insert or update an email account, return account ID."""
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO email_accounts (user_id, user_principal_name, display_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO UPDATE SET
                    user_principal_name = EXCLUDED.user_principal_name,
                    display_name = EXCLUDED.display_name
                RETURNING id
            """, (user_id, upn, display_name))
            account_id = cur.fetchone()[0]
            conn.commit()
        return account_id
    
    def upsert_emails(self, account_id: int, emails: List[Dict]) -> int:
        """Bulk upsert emails, return count of inserted/updated."""
        if not emails:
            return 0
        
        conn = self.connect()
        with conn.cursor() as cur:
            values = []
            for email in emails:
                from_addr = email.get("from", {}).get("emailAddress", {})
                values.append((
                    email.get("id"),
                    account_id,
                    email.get("conversationId"),
                    email.get("subject"),
                    email.get("bodyPreview"),
                    email.get("body", {}).get("content"),
                    email.get("body", {}).get("contentType"),
                    from_addr.get("address"),
                    from_addr.get("name"),
                    Json(email.get("toRecipients", [])),
                    Json(email.get("ccRecipients", [])),
                    Json(email.get("bccRecipients", [])),
                    email.get("receivedDateTime"),
                    email.get("sentDateTime"),
                    email.get("hasAttachments", False),
                    email.get("importance"),
                    email.get("isRead", False),
                    email.get("isDraft", False),
                    email.get("webLink"),
                    Json(email.get("categories", [])),
                    email.get("parentFolderId"),
                    None  # folder_name - would need lookup
                ))
            
            execute_values(cur, """
                INSERT INTO emails (
                    message_id, account_id, conversation_id, subject, body_preview,
                    body_content, body_content_type, from_address, from_name,
                    to_recipients, cc_recipients, bcc_recipients,
                    received_datetime, sent_datetime, has_attachments, importance,
                    is_read, is_draft, web_link, categories, folder_id, folder_name
                ) VALUES %s
                ON CONFLICT (message_id) DO UPDATE SET
                    subject = EXCLUDED.subject,
                    body_preview = EXCLUDED.body_preview,
                    body_content = EXCLUDED.body_content,
                    is_read = EXCLUDED.is_read,
                    categories = EXCLUDED.categories,
                    updated_at = CURRENT_TIMESTAMP
            """, values)
            
            count = cur.rowcount
            conn.commit()
        
        return count
    
    def upsert_attachments(self, email_db_id: int, attachments: List[Dict]) -> int:
        """Insert attachments for an email."""
        if not attachments:
            return 0
        
        conn = self.connect()
        with conn.cursor() as cur:
            values = []
            for att in attachments:
                values.append((
                    email_db_id,
                    att.get("id"),
                    att.get("name"),
                    att.get("contentType"),
                    att.get("size"),
                    att.get("isInline", False),
                    att.get("contentBytes")  # Base64 encoded
                ))
            
            execute_values(cur, """
                INSERT INTO email_attachments (
                    email_id, attachment_id, name, content_type, size, is_inline, content_bytes
                ) VALUES %s
                ON CONFLICT DO NOTHING
            """, values)
            
            count = cur.rowcount
            conn.commit()
        
        return count
    
    def log_sync(
        self,
        account_id: int,
        sync_type: str,
        status: str,
        emails_synced: int = 0,
        error_message: str = None
    ) -> int:
        """Log a sync operation."""
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sync_logs (account_id, sync_type, status, emails_synced, error_message, completed_at)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (account_id, sync_type, status, emails_synced, error_message,
                  datetime.now() if status in ('completed', 'failed') else None))
            log_id = cur.fetchone()[0]
            conn.commit()
        return log_id
    
    def update_account_sync_time(self, account_id: int):
        """Update the last sync timestamp for an account."""
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE email_accounts SET last_sync_at = CURRENT_TIMESTAMP WHERE id = %s
            """, (account_id,))
            conn.commit()
    
    def get_email_stats(self) -> Dict:
        """Get statistics about synced emails."""
        conn = self.connect()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM email_accounts) as accounts,
                    (SELECT COUNT(*) FROM emails) as emails,
                    (SELECT COUNT(*) FROM email_attachments) as attachments,
                    (SELECT MIN(received_datetime) FROM emails) as oldest_email,
                    (SELECT MAX(received_datetime) FROM emails) as newest_email
            """)
            row = cur.fetchone()
            return {
                "accounts": row[0],
                "emails": row[1],
                "attachments": row[2],
                "oldest_email": row[3],
                "newest_email": row[4]
            }


class EmailSyncer:
    """Main email sync orchestrator."""
    
    def __init__(self, db_url: str = None):
        self.graph = MSGraphClient()
        self.db = NeonDB(db_url)
    
    def sync_user(
        self,
        user_id: str,
        upn: str,
        display_name: str,
        folders: List[str] = None,
        since: datetime = None,
        include_attachments: bool = False
    ) -> Dict:
        """Sync emails for a single user."""
        if folders is None:
            folders = ["inbox", "sentitems"]
        
        logger.info(f"Syncing user: {display_name} ({upn})")
        
        # Upsert account
        account_id = self.db.upsert_account(user_id, upn, display_name)
        
        total_synced = 0
        errors = []
        
        for folder in folders:
            try:
                logger.info(f"  Syncing folder: {folder}")
                messages = self.graph.get_user_messages(user_id, folder, since=since)
                
                if messages:
                    count = self.db.upsert_emails(account_id, messages)
                    total_synced += count
                    logger.info(f"    Synced {count} emails from {folder}")
                    
                    # Optionally sync attachments
                    if include_attachments:
                        for msg in messages:
                            if msg.get("hasAttachments"):
                                attachments = self.graph.get_message_attachments(user_id, msg["id"])
                                if attachments:
                                    # Would need to get email DB ID first
                                    pass
                else:
                    logger.info(f"    No new emails in {folder}")
                    
            except Exception as e:
                error_msg = f"Error syncing {folder}: {str(e)}"
                logger.error(f"    {error_msg}")
                errors.append(error_msg)
        
        # Update sync time and log
        self.db.update_account_sync_time(account_id)
        status = "completed" if not errors else "partial"
        self.db.log_sync(account_id, "incremental" if since else "full", status, total_synced,
                        "; ".join(errors) if errors else None)
        
        return {
            "user": upn,
            "account_id": account_id,
            "emails_synced": total_synced,
            "errors": errors
        }
    
    def sync_all_users(
        self,
        user_filter: str = None,
        folders: List[str] = None,
        since: datetime = None,
        max_users: int = None
    ) -> Dict:
        """Sync emails for all users (or filtered subset)."""
        logger.info("Starting full tenant email sync")
        
        # Get all users
        users = self.graph.get_users()
        logger.info(f"Found {len(users)} users in tenant")
        
        # Filter if specified
        if user_filter:
            users = [u for u in users if user_filter.lower() in u.get("userPrincipalName", "").lower()]
            logger.info(f"Filtered to {len(users)} users matching '{user_filter}'")
        
        # Limit if specified
        if max_users:
            users = users[:max_users]
        
        results = []
        for user in users:
            try:
                result = self.sync_user(
                    user_id=user["id"],
                    upn=user.get("userPrincipalName", ""),
                    display_name=user.get("displayName", ""),
                    folders=folders,
                    since=since
                )
                results.append(result)
            except Exception as e:
                logger.error(f"Failed to sync user {user.get('userPrincipalName')}: {e}")
                results.append({
                    "user": user.get("userPrincipalName"),
                    "error": str(e)
                })
        
        # Summary
        total_emails = sum(r.get("emails_synced", 0) for r in results)
        successful = len([r for r in results if "error" not in r])
        
        logger.info(f"Sync complete: {successful}/{len(users)} users, {total_emails} emails")
        
        return {
            "users_processed": len(results),
            "users_successful": successful,
            "total_emails_synced": total_emails,
            "results": results
        }
    
    def get_stats(self) -> Dict:
        """Get current sync statistics."""
        return self.db.get_email_stats()
    
    def close(self):
        """Clean up resources."""
        self.db.close()


def main():
    """Main entry point for CLI usage."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Sync Microsoft Graph emails to Neon PostgreSQL")
    parser.add_argument("--user", help="Sync specific user by UPN or ID")
    parser.add_argument("--filter", help="Filter users by UPN pattern")
    parser.add_argument("--folders", nargs="+", default=["inbox", "sentitems"],
                       help="Mail folders to sync")
    parser.add_argument("--since", help="Only sync emails since date (ISO format)")
    parser.add_argument("--max-users", type=int, help="Maximum number of users to sync")
    parser.add_argument("--stats", action="store_true", help="Show sync statistics")
    parser.add_argument("--db-url", help="Database connection URL")
    
    args = parser.parse_args()
    
    # Parse since date
    since = None
    if args.since:
        since = datetime.fromisoformat(args.since.replace("Z", "+00:00"))
    
    # Initialize syncer
    syncer = EmailSyncer(args.db_url)
    
    try:
        if args.stats:
            stats = syncer.get_stats()
            print("\n📊 Email Sync Statistics:")
            print(f"   Accounts: {stats['accounts']}")
            print(f"   Emails: {stats['emails']}")
            print(f"   Attachments: {stats['attachments']}")
            print(f"   Date range: {stats['oldest_email']} to {stats['newest_email']}")
        
        elif args.user:
            # Sync specific user
            users = syncer.graph.get_users()
            user = next((u for u in users if args.user in (u["id"], u.get("userPrincipalName", ""))), None)
            
            if user:
                result = syncer.sync_user(
                    user_id=user["id"],
                    upn=user.get("userPrincipalName", ""),
                    display_name=user.get("displayName", ""),
                    folders=args.folders,
                    since=since
                )
                print(f"\n✅ Synced {result['emails_synced']} emails for {result['user']}")
            else:
                print(f"❌ User not found: {args.user}")
        
        else:
            # Sync all users
            result = syncer.sync_all_users(
                user_filter=args.filter,
                folders=args.folders,
                since=since,
                max_users=args.max_users
            )
            print(f"\n✅ Sync complete!")
            print(f"   Users: {result['users_successful']}/{result['users_processed']}")
            print(f"   Emails: {result['total_emails_synced']}")
    
    finally:
        syncer.close()


if __name__ == "__main__":
    main()
