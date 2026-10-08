# mistral-document-ai-2512-image-only

5 reads per document. ✗ = wrong value.

## Scorecard

| model | reads | errors | field accuracy | ABA+account accuracy | docs fully right | mean conf (right) | mean conf (wrong) | silent errors (2-pass) | median s | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|---|
| mistral-document-ai-2512-image-only | 30 | 0 | 165/180 (92%) | 60/60 (100%) | 15/30 | 0.91 | 0.95 | 6 in 12 pairs | 6.6 | 0/0 |

## Confidence per run

| Doc | Run | BenName | BenAddr | Bank | BankAddr | ABA | Acct | Sec |
|---|---|---|---|---|---|---|---|---|
| baseline | 0 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 6.6 |
| baseline | 1 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 6.6 |
| baseline | 2 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 6.0 |
| baseline | 3 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 8.9 |
| baseline | 4 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 7.3 |
| repeated_digits | 0 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 7.6 |
| repeated_digits | 1 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 4.7 |
| repeated_digits | 2 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 5.1 |
| repeated_digits | 3 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 8.5 |
| repeated_digits | 4 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 3.4 |
| long_account | 0 | 0.95 | 0.50 | 0.95 | 0.95 | 0.95 | 0.95 | 7.4 |
| long_account | 1 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 5.0 |
| long_account | 2 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 5.0 |
| long_account | 3 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 6.6 |
| long_account | 4 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 4.2 |
| dense_table | 0 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 4.4 |
| dense_table | 1 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 9.7 |
| dense_table | 2 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 8.7 |
| dense_table | 3 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 6.9 |
| dense_table | 4 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 6.3 |
| blurry_scan | 0 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 6.6 |
| blurry_scan | 1 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 4.9 |
| blurry_scan | 2 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 5.1 |
| blurry_scan | 3 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 8.4 |
| blurry_scan | 4 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 5.8 |
| two_page | 0 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 12.2 |
| two_page | 1 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 12.5 |
| two_page | 2 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 7.0 |
| two_page | 3 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 10.0 |
| two_page | 4 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 5.3 |

## Wrong values

| Doc | Field | Expected | Got | Times |
|---|---|---|---|---|
| baseline | beneficiary_name | `Brightwater Escrow Services Client Trust Account` | `Brightwater Escrow Services` | 5 |
| blurry_scan | beneficiary_name | `Brightwater Escrow Services Client Trust Account` | `Brightwater Escrow Services` | 5 |
| repeated_digits | beneficiary_name | `Hollowell & Gibbs Settlement Account` | `Hollowell & Gibbs` | 5 |
