# Microsoft Graph Email Sync

Sync emails from Microsoft 365 / Azure AD to a Neon PostgreSQL database using Microsoft Graph API with application permissions.

## Features

- **Full tenant email sync** - Sync emails from all users in your organization
- **Incremental sync** - Only sync new emails since last sync
- **Multiple folders** - Sync inbox, sent items, and other folders
- **Attachment support** - Optionally sync email attachments
- **PostgreSQL storage** - Store emails in Neon serverless PostgreSQL
- **Sync logging** - Track sync history and statistics

## Prerequisites

1. **Azure AD App Registration** with the following application permissions:
   - `Mail.Read` - Read mail in all mailboxes
   - `Mail.ReadBasic.All` - Read basic mail properties
   - `User.Read.All` - Read all users' profiles

2. **Neon PostgreSQL Database** - Create a project at [neon.tech](https://neon.tech)

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/your-org/msgraph-email-sync.git
cd msgraph-email-sync
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your credentials
```

Required environment variables:
- `AZURE_TENANT_ID` - Your Azure AD tenant ID
- `AZURE_CLIENT_ID` - Your app registration client ID
- `AZURE_CLIENT_SECRET` - Your app registration client secret
- `DATABASE_URL` - Neon PostgreSQL connection string

### 4. Initialize the database

The database schema is automatically created when you first run the sync. Tables created:
- `email_accounts` - User accounts being synced
- `emails` - Email messages with full metadata
- `email_attachments` - Email attachments (optional)
- `sync_logs` - Sync operation history

## Usage

### Sync all users

```bash
python src/email_sync.py
```

### Sync specific user

```bash
python src/email_sync.py --user user@domain.com
```

### Sync with filters

```bash
# Only sync users matching pattern
python src/email_sync.py --filter "@domain.com"

# Limit number of users
python src/email_sync.py --max-users 10

# Sync specific folders
python src/email_sync.py --folders inbox sentitems drafts

# Incremental sync (since date)
python src/email_sync.py --since 2024-01-01
```

### View statistics

```bash
python src/email_sync.py --stats
```

## Database Schema

### email_accounts
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| user_id | VARCHAR | Azure AD user ID |
| user_principal_name | VARCHAR | User email/UPN |
| display_name | VARCHAR | User display name |
| created_at | TIMESTAMP | Account creation time |
| last_sync_at | TIMESTAMP | Last successful sync |

### emails
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| message_id | VARCHAR | MS Graph message ID |
| account_id | INTEGER | FK to email_accounts |
| conversation_id | VARCHAR | Conversation thread ID |
| subject | TEXT | Email subject |
| body_preview | TEXT | Body preview (snippet) |
| body_content | TEXT | Full body content |
| from_address | VARCHAR | Sender email |
| from_name | VARCHAR | Sender name |
| to_recipients | JSONB | To recipients array |
| cc_recipients | JSONB | CC recipients array |
| received_datetime | TIMESTAMP | When received |
| sent_datetime | TIMESTAMP | When sent |
| has_attachments | BOOLEAN | Has attachments flag |
| importance | VARCHAR | Email importance |
| is_read | BOOLEAN | Read status |
| folder_id | VARCHAR | Mail folder ID |

### sync_logs
| Column | Type | Description |
|--------|------|-------------|
| id | SERIAL | Primary key |
| account_id | INTEGER | FK to email_accounts |
| sync_type | VARCHAR | full/incremental |
| status | VARCHAR | completed/failed/partial |
| emails_synced | INTEGER | Count of emails synced |
| error_message | TEXT | Error details if failed |
| started_at | TIMESTAMP | Sync start time |
| completed_at | TIMESTAMP | Sync completion time |

## API Reference

### EmailSyncer

```python
from src.email_sync import EmailSyncer

syncer = EmailSyncer(db_url="postgresql://...")

# Sync single user
result = syncer.sync_user(
    user_id="user-guid",
    upn="user@domain.com",
    display_name="User Name",
    folders=["inbox", "sentitems"],
    since=datetime(2024, 1, 1)
)

# Sync all users
result = syncer.sync_all_users(
    user_filter="@domain.com",
    max_users=100
)

# Get statistics
stats = syncer.get_stats()
```

### MSGraphClient

```python
from src.email_sync import MSGraphClient

client = MSGraphClient()

# Get all users
users = client.get_users()

# Get user's messages
messages = client.get_user_messages(
    user_id="user-guid",
    folder="inbox",
    top=100
)

# Get mail folders
folders = client.get_mail_folders(user_id="user-guid")
```

## Scheduled Sync

For automated syncing, use cron or a scheduler:

```bash
# Sync every hour
0 * * * * cd /path/to/msgraph-email-sync && python src/email_sync.py --since $(date -d '1 hour ago' -Iseconds)
```

Or use GitHub Actions (see `.github/workflows/sync.yml`).

## Security Considerations

- **Application permissions** - This uses app-only authentication, which has access to all mailboxes
- **Least privilege** - Only request the permissions you need
- **Secret management** - Use environment variables or a secrets manager
- **Data encryption** - Neon uses TLS for connections; consider encrypting sensitive data at rest

## License

MIT License
