# mistral-document-ai-2512

5 reads per document. ✗ = wrong value.

## Scorecard

| model | reads | errors | field accuracy | ABA+account accuracy | docs fully right | mean conf (right) | mean conf (wrong) | silent errors (2-pass) | median s | tokens in/out |
|---|---|---|---|---|---|---|---|---|---|---|
| mistral-document-ai-2512 | 30 | 0 | 166/180 (92%) | 60/60 (100%) | 16/30 | 0.91 | 0.95 | 5 in 12 pairs | 2.7 | 0/0 |

## Confidence per run

| Doc | Run | BenName | BenAddr | Bank | BankAddr | ABA | Acct | Sec |
|---|---|---|---|---|---|---|---|---|
| baseline | 0 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.8 |
| baseline | 1 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.9 |
| baseline | 2 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.5 |
| baseline | 3 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.7 |
| baseline | 4 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.7 |
| repeated_digits | 0 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.9 |
| repeated_digits | 1 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 3.0 |
| repeated_digits | 2 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 2.4 |
| repeated_digits | 3 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 2.3 |
| repeated_digits | 4 | 0.95 ✗ | 0.95 | 0.95 | 0.95 | 0.95 | 0.95 | 2.5 |
| long_account | 0 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 2.5 |
| long_account | 1 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 2.7 |
| long_account | 2 | 1.00 | 0.50 | 1.00 | 1.00 | 1.00 | 1.00 | 2.2 |
| long_account | 3 | 1.00 | 0.50 | 0.90 | 0.90 | 0.90 | 0.90 | 2.5 |
| long_account | 4 | 0.95 | 0.50 | 0.95 | 0.95 | 0.95 | 0.95 | 2.8 |
| dense_table | 0 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 3.1 |
| dense_table | 1 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 3.0 |
| dense_table | 2 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 3.0 |
| dense_table | 3 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.8 |
| dense_table | 4 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 3.0 |
| blurry_scan | 0 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.3 |
| blurry_scan | 1 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.8 |
| blurry_scan | 2 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.6 |
| blurry_scan | 3 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.5 |
| blurry_scan | 4 | 0.95 ✗ | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.9 |
| two_page | 0 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.5 |
| two_page | 1 | 1.00 | 0.90 | 0.95 | 0.95 | 0.95 | 0.95 | 2.5 |
| two_page | 2 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.3 |
| two_page | 3 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.8 |
| two_page | 4 | 0.95 | 0.70 | 0.95 | 0.95 | 0.95 | 0.95 | 2.8 |

## Wrong values

| Doc | Field | Expected | Got | Times |
|---|---|---|---|---|
| baseline | beneficiary_name | `Brightwater Escrow Services Client Trust Account` | `Brightwater Escrow Services` | 5 |
| blurry_scan | beneficiary_name | `Brightwater Escrow Services Client Trust Account` | `Brightwater Escrow Services` | 5 |
| repeated_digits | beneficiary_name | `Hollowell & Gibbs Settlement Account` | `Hollowell & Gibbs` | 4 |
