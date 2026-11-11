# Decisions

## Energy consumption comes from the meter registers

Originally the daily summary was the only consumption source and meter readings were
display-only. Live data showed that `resumo/ultimasemana` reports partial values for the
most recent days (5.4 and 8.0 kWh where the registers show 25.4 and 24.3 kWh), and those
partial values were written into the Energy history. For complete days both sources
agree to the watt-hour. The cumulative registers in `leituras` are complete one day
earlier, cover about three years, and carry the per-period registers the invoice uses,
so they now feed the statistics. The summary still feeds the latest-daily-consumption
sensor. Fifteen-minute samples remain out of scope for the reasons given before:
pagination, completeness rules, DST interval handling and more requests.

The meter-reading sensor stays display-only without a `state_class`: its delayed
operator date cannot be represented by the current entity-state timestamp, so it must
not create a second Energy history. No local reading history is kept; the recorder's
statistics are the only state.

Summary and meter-reading failures are tracked separately. Either source may update on
its own; only failure of both makes the coordinator update fail. Authentication failure
from either source starts reauthentication.

## Energy uses an external statistic

Historical daily values are imported as
`eem_online:<contract>_consumption`, with `state` equal to the day's consumption and
`sum` equal to cumulative known consumption. Writing old days as the current state of a
sensor would give recorder the wrong timestamps and would not backfill Energy history.

## Corrections rewrite a 30-day overlapping window

Every update fetches the readings from 30 days ago, or from the newest imported day after
a longer outage (bounded to one year), turns them into daily differences, and upserts
every day from the first fetched reading onwards on top of the sum of the last row
before it. Absolute rows make an identical retry idempotent, and a rewrite never leaves
a jump in the cumulative sum. The `import_history` action uses the same path with a
user-chosen start date. There is no additional Store or history cache; an interrupted
import is retried by the next synchronization.

## Costs are imported, not priced by the Energy Dashboard

The Energy Dashboard only prices an energy entity through an automatically created cost
sensor, which does not exist for external statistics, and its fixed prices cannot express
a VAT rate that changes after 200 kWh per 30 days. The integration therefore imports one
cost statistic per register, computed with dated prices, and a zero-energy fixed-charges
statistic whose cost statistic carries the daily fixed charges. Costs are recomputed with
the energy on every window rewrite and by `import_history`.

## The API client stays inside the integration

The reverse-engineered API is small and uses one login plus two read endpoints. A
separately published client library would add release and compatibility work without
reducing the MVP implementation.
