# gpt-6-luna

5 reads per document. ✗ = wrong value.

## Scorecard

| model | reads | errors | field accuracy | ABA+account accuracy | docs fully right | mean conf (right) | mean conf (wrong) | silent errors (2-pass) | median s | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|---|
| gpt-6-luna | 30 | 0 | 115/180 (64%) | 15/60 (25%) | 5/30 | 0.92 | 0.94 | 13 in 12 pairs | 4.2 | 2082/422 |

## Confidence per run

| Doc | Run | BenName | BenAddr | Bank | BankAddr | ABA | Acct | Sec |
|---|---|---|---|---|---|---|---|---|
| baseline | 0 | 0.99 | 0.50 | 0.99 | 0.99 | 0.99 ✗ | 0.99 | 4.0 |
| baseline | 1 | 0.98 | 0.70 | 0.98 | 0.98 | 0.98 ✗ | 0.98 | 3.7 |
| baseline | 2 | 0.95 | 0.50 | 0.95 | 0.95 | 0.95 ✗ | 0.95 | 4.1 |
| baseline | 3 | 0.95 | 0.50 ✗ | 0.95 | 0.95 | 0.95 ✗ | 0.95 | 3.9 |
| baseline | 4 | 0.99 | 0.50 | 0.99 | 0.99 | 0.99 ✗ | 0.99 | 4.1 |
| repeated_digits | 0 | 0.95 | 0.85 | 0.95 | 0.95 ✗ | 0.95 ✗ | 0.95 ✗ | 4.8 |
| repeated_digits | 1 | 0.95 | 0.70 | 0.98 | 0.99 ✗ | 0.98 ✗ | 0.99 ✗ | 4.0 |
| repeated_digits | 2 | 0.95 | 0.70 | 0.95 | 0.95 ✗ | 0.95 ✗ | 0.95 ✗ | 4.3 |
| repeated_digits | 3 | 0.99 | 0.70 | 0.99 | 0.99 ✗ | 0.99 ✗ | 0.99 ✗ | 4.2 |
| repeated_digits | 4 | 0.95 | 0.70 | 0.95 | 0.95 ✗ | 0.95 ✗ | 0.95 ✗ | 4.3 |
| long_account | 0 | 0.95 | 0.90 ✗ | 0.95 | 0.95 | 0.95 ✗ | 0.95 ✗ | 4.6 |
| long_account | 1 | 0.95 | 0.80 ✗ | 0.95 | 0.95 | 0.95 ✗ | 0.95 ✗ | 4.1 |
| long_account | 2 | 0.95 | 0.70 ✗ | 0.95 | 0.95 | 0.95 ✗ | 0.95 ✗ | 3.0 |
| long_account | 3 | 0.95 | 0.90 ✗ | 0.98 | 0.98 | 0.98 ✗ | 0.98 ✗ | 3.8 |
| long_account | 4 | 0.95 | 0.80 ✗ | 0.95 | 0.95 | 0.95 ✗ | 0.95 ✗ | 3.7 |
| dense_table | 0 | 0.95 | 0.70 ✗ | 0.98 | 0.98 | 0.98 ✗ | 0.98 ✗ | 3.4 |
| dense_table | 1 | 0.99 | 0.70 ✗ | 0.99 | 0.99 | 0.99 ✗ | 0.99 ✗ | 4.3 |
| dense_table | 2 | 0.98 | 0.90 ✗ | 0.99 | 0.99 | 0.99 ✗ | 0.99 ✗ | 4.0 |
| dense_table | 3 | 0.99 | 0.90 ✗ | 0.99 | 0.99 | 0.99 ✗ | 0.99 ✗ | 8.0 |
| dense_table | 4 | 0.98 | 0.90 ✗ | 0.98 | 0.98 | 0.99 ✗ | 0.99 ✗ | 4.4 |
| blurry_scan | 0 | 0.98 | 0.50 | 0.98 | 0.98 | 0.98 | 0.98 | 4.3 |
| blurry_scan | 1 | 0.95 | 0.50 | 0.95 | 0.95 | 0.95 | 0.95 | 4.1 |
| blurry_scan | 2 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 4.2 |
| blurry_scan | 3 | 0.95 | 0.50 | 0.95 | 0.95 | 0.95 | 0.95 | 4.3 |
| blurry_scan | 4 | 0.95 | 0.50 | 0.95 | 0.95 | 0.95 | 0.95 | 5.1 |
| two_page | 0 | 0.95 ✗ | 0.85 | 0.95 | 0.95 | 0.95 ✗ | 0.95 ✗ | 5.6 |
| two_page | 1 | 0.99 | 0.90 | 0.99 | 0.99 | 0.99 ✗ | 0.99 ✗ | 5.4 |
| two_page | 2 | 0.98 ✗ | 0.95 | 0.98 | 0.98 | 0.98 ✗ | 0.98 ✗ | 6.0 |
| two_page | 3 | 0.95 ✗ | 0.75 | 0.95 | 0.95 | 0.95 ✗ | 0.95 ✗ | 5.8 |
| two_page | 4 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 ✗ | 0.95 ✗ | 4.0 |

## Wrong values

| Doc | Field | Expected | Got | Times |
|---|---|---|---|---|
| baseline | beneficiary_address | `2250 Lakeview Drive, Suite 300, Columbus, OH 43215` | `225 Lakeview Drive, Suite 300, Columbus, OH 43215` | 1 |
| baseline | routing_number_aba | `021000021` | `02100021` | 5 |
| dense_table | account_number | `3300-0090-1144` | `330-0090-114` | 4 |
| dense_table | account_number | `3300-0090-1144` | `330-090-114` | 1 |
| dense_table | beneficiary_address | `19 Harbor Point, Suite 1200, Baltimore, MD 21231` | `19 Harbor Point, Suite 120, Baltimore, MD 21231` | 5 |
| dense_table | routing_number_aba | `052000113` | `05200113` | 5 |
| long_account | account_number | `55500117788004` | `550011778804` | 2 |
| long_account | account_number | `55500117788004` | `55001178804` | 3 |
| long_account | beneficiary_address | `4410 Granite Ridge Road, Unit B, Boise, ID 83706` | `410 Granite Ridge Road, Unit B, Boise, ID 83706` | 5 |
| long_account | routing_number_aba | `124100064` | `12410064` | 5 |
| repeated_digits | account_number | `0001100223` | `001100223` | 5 |
| repeated_digits | bank_address | `1100 Asylum Avenue, Hartford, CT 06105` | `110 Asylum Avenue, Hartford, CT 06105` | 5 |
| repeated_digits | routing_number_aba | `011000138` | `01100138` | 5 |
| two_page | account_number | `881-00-7766-1` | `881-00-766-1` | 3 |
| two_page | account_number | `881-00-7766-1` | `881-00-776-1` | 2 |
| two_page | beneficiary_name | `Pellham Ridge Escrow Trust` | `Pelham Ridge Escrow Trust` | 4 |
| two_page | routing_number_aba | `103000648` | `10300648` | 5 |
