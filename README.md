# EEM Online for Home Assistant

> **Unofficial project.** This community integration is not affiliated with,
> endorsed by, or supported by Empresa de Electricidade da Madeira, S.A. (EEM).
> The EEM name and logo are used only to identify the service with which this
> integration interoperates.

EEM Online is a minimal custom integration for electricity consumption published by
Empresa de Electricidade da Madeira. It configures one login and one contract through
the Home Assistant UI.

The integration polls every 12 hours. It exposes the latest available daily consumption
and cumulative meter reading, each with its operator date as an attribute. Daily
consumption calculated from the cumulative meter readings is imported as external
long-term statistics for the Energy Dashboard, in total and per meter register.

## Current scope

- one EEM login and one contract per config entry;
- the latest daily consumption from `resumo/ultimasemana` for the status sensor;
- daily Energy statistics from the cumulative registers in `leituras`, rewritten over a
  30-day overlapping window and reaching back up to a year after a longer outage;
- two read-only sensors with `consumption_date` and `reading_date` attributes;
- four external statistics: `eem_online:<contract>_consumption` (total) and
  `eem_online:<contract>_consumption_vazio`, `_ponta`, `_cheias` (registers 1 to 3);
- cost statistics including VAT for Vazio, Ponta and Cheias, and a fixed-charges source;
- the `eem_online.import_history` action to rebuild the statistics from a start date.

Fifteen-minute samples, billing, prices, production, export, one entry managing multiple
contracts, options, and repair flows are outside this version.

## Installation

EEM Online requires Home Assistant 2026.9.2 or newer and HACS 2.0.5 or newer.

### Install through HACS

[![Open your Home Assistant instance and open the EEM Online repository in HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=zewelor&repository=ha-eem-pt&category=integration)

1. Select the button above and open the link in your Home Assistant instance.
2. In HACS, select **Download**.
3. Restart Home Assistant.

If the button does not open the repository, add it manually:

1. Open HACS and select the three-dot menu in the top-right corner.
2. Select **Custom repositories**.
3. Enter `https://github.com/zewelor/ha-eem-pt` and select **Integration** as the
   category.
4. Select **Add**, open **EEM Online**, and select **Download**.
5. Restart Home Assistant.

### Add the integration

[![Open your Home Assistant instance and start setting up EEM Online](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=eem_online)

Select the button above, or open **Settings > Devices & services > Add integration**
and search for **EEM Online**.

Enter the EEM Online username, password, and numeric electricity contract number. The
integration validates the credentials and checks that the configured contract endpoint
returns a supported response before creating the entry.

To monitor another contract from the same EEM Online account, add the integration again
with the same credentials and the other contract number. Home Assistant keeps each
contract as an independent integration entry with its own sensors and Energy statistic.

## Energy Dashboard

Open **Settings > Dashboards > Energy**, add an electricity grid consumption source,
and select the statistic named **EEM Online `<contract>` consumption**. To see the
tariff periods separately, add the three register statistics as grid sources instead of
the total; never add the total and the registers together. The Energy
Dashboard uses the imported historical statistic; the latest-daily-consumption sensor
is only a compact status view. The meter-reading sensor is also for display only and
must not be added as a second consumption source.

### Costs

The integration also imports cost statistics in EUR: `eem_online:<contract>_cost_vazio`,
`_cost_ponta` and `_cost_cheias`, and `_cost_fixed` for the fixed charges. Select each
cost statistic as **Use an entity tracking the total costs** for its register source.
The fixed charges get their own grid source, `eem_online:<contract>_fixed_charges`, which
always reports 0 kWh, so they appear in the dashboard's costs without adding energy.

Costs follow the itemization of the EEM invoice: the active energy price of each period,
the reduced VAT rate (4 %) on 200 kWh per 30 days shared by the periods in proportion to
their consumption, the normal rate (22 %) on the rest, and IEC at 0.001 EUR/kWh plus
22 %. The fixed charges are the contracted power per day plus 22 %, the operation fee of
0.08 EUR per month plus 22 % and the audiovisual contribution of 2.85 EUR per month plus
4 %, spread over the days of the month. The price table in `coordinator/tariffs.py`
covers one contract type: RAM, BTN tri-horária, 6.9 kVA. Add a dated entry when ERSE
publishes new prices and run **Import history** to recalculate.

### Import history

New installations only import the last 30 days. To import older days, open
**Developer tools > Actions**, select **EEM Online: Import history**, choose the entry
and a start date, and run it. EEM Online keeps about three years of meter readings. The
action replaces the statistics from the start date onwards and returns the first and
last imported day and register value of each statistic, which can be compared with an
EEM invoice. Create a Home Assistant backup first.

## Data assumptions

EEM Online does not publish a supported public API. The MVP currently interprets the
sum of `consumoCheias`, `consumoVazio`, and `consumoPonta` as kWh for the civil date in
`data`, in the `Atlantic/Madeira` time zone. Local PoC observations support that shape,
but the daily-summary date semantics still need confirmation. A live, anonymized
`leituras` check confirmed the `data` timestamp, numeric `totalRegistadores`, and
pagination shape; the portal labels meter readings in kWh and reports production in a
separate field. Zero daily consumption is not imported because the weekly response does
not prove that a zero-valued day is complete.

A reading dated D is the register value at the start of D, so the consumption of D is
the reading of D+1 minus the reading of D. Live data confirmed this: for complete days
the differences of `totalRegistadores` match the weekly summary to the watt-hour, while
the summary still reported partial values for the two most recent days. Days without a
reading share the difference to the next reading evenly, and a decreasing register
counts as zero. `totalRegistador1` to `totalRegistador3` were matched to Vazio, Ponta
and Cheias against one tri-horária invoice. The portal's own per-period split in the
weekly summary differs from the registers by one or two kWh per day; the registers are
what the invoice uses.

## Development

The project structure and development tooling are based on the
[HACS Integration Blueprint](https://github.com/jpawlowski/hacs.integration_blueprint).

```bash
script/setup/bootstrap
script/lint
script/type-check
script/hassfest
script/test
```
