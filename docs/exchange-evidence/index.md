---
layout: default
title: Exchange Evidence Search Results
---

# Exchange Evidence Search Results

**Source:** Exchange Mailbox Records (Neon DB: exchange_sync)
**Extracted:** 2026-02-22 22:39
**Database Range:** 2014-12-07 to 2026-02-18
**Total Messages in DB:** ~1M across 112 users

---

## Evidence Chains

| Chain | Messages | Description | Application |
|-------|----------|-------------|-------------|
| [sage_fraud](./sage_fraud.md) | 50 | Sage ownership transfer via false death claim | App 1 (Civil/Criminal), App 2 (CIPC), App 3 (Commercial Crime) |
| [shopify_hijacking](./shopify_hijacking.md) | 50 | Shopify revenue stream diversion | App 1 (Civil/Criminal), App 3 (Commercial Crime/Tax Fraud) |
| [rynette_denovo](./rynette_denovo.md) | 50 | Rynette-De Novo fabricated accounts | App 2 (CIPC), App 3 (Commercial Crime) |
| [trust_forgery](./trust_forgery.md) | 50 | Trust amendment forgery & backdated appointment | App 1 (Civil/Criminal), App 2 (CIPC) |
| [card_cancellation](./card_cancellation.md) | 50 | Card cancellation retaliation pattern | App 1 (Civil/Criminal) |
| [contempt](./contempt.md) | 12 | Contempt application based on void order | App 1 (Civil/Criminal) |
| [ketoni_motive](./ketoni_motive.md) | 37 | R18.75M Ketoni payout motive | App 1 (Civil/Criminal), App 3 (NPA Tax Fraud) |
| [popia](./popia.md) | 30 | POPIA violation & retaliation evidence | App 2 (POPIA Criminal Complaint) |

---

## How to Use This Evidence

1. **Each chain** contains chronologically ordered email messages extracted from the Exchange mailbox database
2. **Message IDs** can be used to retrieve full message content from the Neon DB (`exchange_sync.messages`)
3. **Cross-reference** with existing evidence in the `evidence/` directory for corroboration
4. **Legal relevance** is mapped to the three applications (Civil/Criminal, CIPC/POPIA, Commercial Crime/Tax Fraud)

## Database Connection

Evidence is stored in Neon PostgreSQL:
- **Project:** `b2bkp-exchange-sync` (square-butterfly-04468397)
- **Schema:** `exchange_sync`
- **Table:** `messages` (~1M rows)
- **Connection:** Use `CONNECT` environment variable (neonexo1)
