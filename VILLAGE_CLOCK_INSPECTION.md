# Village meter clock inspection

The user confirmed watts and Lebanese local time with summer time for all
seven village sources on November 9, 2026. The original March workbooks were
then inspected directly, without changing or excluding their readings.

## Observed March 30 2025 transition

| Sources | Missing half-hour timestamps | Other findings |
| --- | --- | --- |
| Households 1, 2 and 3; Industrial 1, 2 and 3 | 00:00 and 00:30 | Sequence moves from March 29 23:30 to March 30 01:00; consistent with the reported Lebanese clock transition |
| Municipality | 06:00 and 06:30 | Midnight readings are present; this differs from the other six sources and remains unexplained |

Every March workbook has 1,486 observations, starts March 1 at 00:00, and
ends March 31 at 23:30. No duplicated half-hour timestamps were found.
March 30 has 46 observations in each file. Those equal counts alone do not
establish equal clock behavior; the missing intervals occur at different times.

The Municipality difference could reflect a clock/export issue or missing
readings. This inspection does not establish its cause and does not justify
applying a six-hour shift. The reported timezone remains in configuration,
with a separate conflict flag that blocks weather alignment until clarified.

## Approved first experiment

After reviewing these findings, the user approved a six-site comparison:
fit on April, select settings on May, refit April-May, and evaluate June.
Municipality stays pending. The experiment makes no forecast at the missing
March midnight and requires no DST-date correction. Earlier recorded history
is retained only for exact historical lag lookups; missing hours are not filled.

No March date was deleted from the original data. No timestamp was shifted.
July final-test data were not used. Detailed source observations and raw cell
types are recorded locally in `outputs/march_clock_inspection.json`.
