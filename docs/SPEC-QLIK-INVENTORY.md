# SPEC-QLIK-INVENTORY: Full App Inventory (Live from API — 2026-03-12)

## Spaces (12 total, 7 relevant for portal)

| Space | ID | Type | Portal Use |
|-------|-----|------|-----------|
| UNLK - Space | `6970e23a54e53a9499619602` | shared | Main multi-team dashboards |
| DFW | `699f0707d4a18cc699e64291` | shared | DFW division reports |
| CORP | `699f07a3199eda7f6c19a64a` | shared | CORP division reports |
| Sales | `699f09a2e0110a978883e9c5` | shared | Sales team reports |
| Carrier Procurement | `699f09fc9d62fa1be769173f` | shared | Carrier/procurement reports |
| IT-DevS | `691c89e016dc4716594a664d` | shared | IT & X-RAY reports |
| Pricing | `69149450bb84486fc7a2423f` | shared | Pricing/spot reports |
| Mobile | `699f0c0c46307c9a8feb9076` | shared | EXCLUDED — mobile copies only |
| Automations | `69aeef7311085172005bb88e` | shared | EXCLUDED — automation workflows |
| IT-Dev | `6914946287480ed3c0ca81f4` | data | EXCLUDED — data connections |
| IT-DevM | `69149473244919c7ab427aa5` | managed | EXCLUDED — dev/staging |
| General-UNILINK | `69149273cf43c18e32d3d3c3` | data | EXCLUDED — data connections |

---

## Production Apps (20 — to be embedded in portal)

### Executive Category
| # | Name | App ID | Sheet ID | Space | Default Roles |
|---|------|--------|----------|-------|---------------|
| 1 | Executive Report | `e4d975eb-e8ca-4727-8a9a-50db58907ef7` | `c77110fc-e146-4bbb-9d47-f534c2ac7803` | UNLK - Space | executive, dfw, corp |
| 2 | DIRECT COMPARE | `4a8e2ffd-b049-4853-b716-195d568aaf11` | `ab318e19-d514-4134-b809-5f0a808a97db` | UNLK - Space | executive, dfw, corp |
| 3 | DFW Executive Report | `7d9b7063-a626-4a8e-b45c-adf8d70cd8e8` | `5af93eec-2371-42d8-9b47-6e2403cdc3db` | DFW | executive, dfw |
| 4 | DFW X-RAY | `9c709f27-30ec-4fb2-bd21-8a2db49426ac` | `0ced6dcb-1cd8-4843-a3c7-68a364e46aac` | DFW | executive, dfw |
| 5 | CORP X-RAY | `4b45853f-057b-4710-a4b8-38a98856cd5e` | `0ced6dcb-1cd8-4843-a3c7-68a364e46aac` | IT-DevS | executive, corp |

### Finance Category
| # | Name | App ID | Sheet ID | Space | Default Roles |
|---|------|--------|----------|-------|---------------|
| 6 | Budget Follow-up | `45fbe2ad-ef79-40a3-89ff-37ca6ddf64fb` | `b6711d0b-be56-4f2d-8c0c-35fff13480d9` | UNLK - Space | executive, finance |
| 7 | Budget - Sales | `3abf5bb5-557a-437c-8813-ba128eb83f9b` | `gNtJ` | Sales | executive, finance, sales |

### Operations Category
| # | Name | App ID | Sheet ID | Space | Default Roles |
|---|------|--------|----------|-------|---------------|
| 8 | Customer Scorecard | `de4c1a28-5e6a-465d-a351-59f99950a5d4` | `f0dd9fa9-4898-4c14-a6bc-6db60357070f` | UNLK - Space | executive, operations |
| 9 | Carrier Savings Dashboard | `a12b7dea-9226-40a8-b0ef-ba8e8d9087b8` | `e332c952-ad92-4625-b2b6-eec3347cd8ba` | Carrier Procurement | executive, operations |
| 10 | Available | `9ba464ca-b42f-43bd-86cc-fbda730f881b` | *(TBD — needs sheet ID)* | UNLK - Space | executive, operations |
| 11 | Customer Attrition Detail | `0857253a-9c3d-4c37-b02f-2ef5faf25705` | *(TBD — needs sheet ID)* | IT-DevS | executive, operations, sales |
| 12 | Spot Details by Express Module | `b4f70f83-36b8-4426-a9b3-ca26f25b55f4` | `65a2b752-0c2c-4024-a733-6cd3057a08bd` | Pricing | executive, operations |
| 13 | RFP Performance Tracker | `6df25048-2917-43e9-a944-a48cc355fdb4` | *(TBD — needs sheet ID)* | Pricing | executive, operations |

### Sales Category
| # | Name | App ID | Sheet ID | Space | Default Roles |
|---|------|--------|----------|-------|---------------|
| 14 | Attrition to Sales | `9b669acd-bf18-4467-9dbc-adeaec537670` | `XPfek` | Sales | executive, sales |
| 15 | Attrition Week-Over-Week | `4e326aa5-3d7a-4802-a792-56e28a35fdd6` | `0a1d1a73-bd89-41a5-b105-5b965788a023` | Sales | executive, sales |
| 16 | Awards Tracker | `949cafc8-cd79-4058-a528-cd4b330d9298` | `fae4a96e-3ed3-447a-abda-be899d0d0dab` | UNLK - Space | executive, sales |

### HR Category
| # | Name | App ID | Sheet ID | Space | Default Roles |
|---|------|--------|----------|-------|---------------|
| 17 | HR - IT Report | `c51e72d7-ca8a-497a-a48e-7b185b90cca3` | `mjGJk` | IT-DevS | executive, hr |
| 18 | HR - Access Log Doors | `4573ff42-c0b5-48ef-9945-20861b7a6f63` | *(TBD — needs sheet ID)* | IT-DevS | executive, hr, it |

### IT Category
| # | Name | App ID | Sheet ID | Space | Default Roles |
|---|------|--------|----------|-------|---------------|
| 19 | Vonage VoIP Calls | `3e30136b-050a-4f19-83ab-17a7d55a2fc3` | `NfAFQFz` | IT-DevS | executive, it |
| 20 | IT Managed Services | `86da731f-577f-45d3-9d40-c416649a4937` | `RqXzx` (Incidents), `8aae69c7-d3be-4759-91aa-4f31960f2155` (Service Requests) | IT-DevS | executive, it |

---

## Excluded Apps (14 — NOT for portal embedding)

### Mobile Copies (10)
| Name | App ID | Space |
|------|--------|-------|
| (Mob) Executive | `a942067d-32e7-4805-b1f1-36764bcf578a` | Mobile |
| (Mob) Budget Follow-up | `56d883e0-69b0-4500-ae16-2745e374760f` | Mobile |
| (Mob) DIRECT COMPARE | `aa25d6c1-c18f-49a7-8ae3-2cdc8a5d7a3a` | Mobile |
| (Mob) Carrier Savings Dashboard | `10b0a4a6-593f-429d-98e9-f7379603ca8e` | Mobile |
| (Mob) Customer Scorecard | `6e7a2f51-6d5a-464a-871b-42a395fa872f` | Mobile |
| (Mob) Spot Details by Express Module | `6339df0f-7487-4737-9ac6-7b45a7e8bf93` | Mobile |
| (Mob) Attrition to Sales | `a9457bc4-8fbb-4f4f-83d6-62c6eae9107c` | Mobile |
| (Mob) Available | `069e3865-d19e-442b-82ff-7a89ef6cb704` | Mobile |
| (Mob) Awards Tracker | `651f789a-f9a4-44ad-9ce3-301a1a3dc2ef` | Mobile |
| (Mob) Attrition Week-Over-Week | `b2faa2ec-a923-4f27-9b18-0fd5cebd962c` | Mobile |

### Development/Personal (4)
| Name | App ID | Location |
|------|--------|----------|
| BK Financial Report | `cbcaaf6e-21df-4d87-a22c-cd3fbe0b2ddb` | Personal (dataflow-prep) |
| Financial File for Qlik | `74b19270-1444-4064-9b6c-43050c933639` | Personal |
| One Note transaction | `894fcfdf-4874-4f49-9b79-e5a69eafeecf` | Personal |
| Carrier Savings Dashboard (old) | `76a853bf-37bc-414e-8ca4-f622e3037a9d` | IT-DevM (staging) |

---

## Sheet IDs Needing Discovery

These apps were found via API but their sheet IDs are not in the inventory files. They need to be fetched via the Qlik Engine WebSocket API or by opening each app in the browser:

1. **Available** (`9ba464ca-b42f-43bd-86cc-fbda730f881b`)
2. **Customer Attrition Detail** (`0857253a-9c3d-4c37-b02f-2ef5faf25705`)
3. **RFP Performance Tracker** (`6df25048-2917-43e9-a944-a48cc355fdb4`)
4. **HR - Access Log Doors** (`4573ff42-c0b5-48ef-9945-20861b7a6f63`)

### How to Get Sheet IDs:
```bash
# Via browser: open the app, navigate to the sheet, copy sheet ID from URL
# URL format: https://mb01txe2h9rovgh.us.qlikcloud.com/sense/app/{appId}/sheet/{sheetId}

# Or via Engine WebSocket API (requires websocket library):
# See /BOT/qlik-api/dashboards/carrier-savings/diagnose_sheet.py for example
```

---

## Embed URL Reference

Each report's iframe URL (for reference only — portal uses `<qlik-embed>` instead):
```
https://mb01txe2h9rovgh.us.qlikcloud.com/single/?appid={APP_ID}&sheet={SHEET_ID}&theme=horizon&opt=ctxmenu,currsel
```

Common URL parameters:
- `theme=horizon` — Qlik's clean light theme
- `opt=ctxmenu` — enable right-click context menu
- `opt=currsel` — show current selections bar
- `select=$::FieldName,Value` — pre-select a filter value
- `bookmark={ID}` — apply a saved bookmark
