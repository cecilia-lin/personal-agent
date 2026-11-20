# Senso answer key — desk-light repairability

This file is our test sheet. **Do not upload it to Senso.** Upload only the four `*_spec_v1.md` files.

Claims match `repairability_claim()` in `apps/api/app/integrations/senso.py`.

| # | Product | Claim to check | Expected verdict | Expected supporting sentence | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|---|---|---|
| 1 | arc-light | Arc desk light has a replaceable bulb. | verified | "The Arc desk light bulb is user-replaceable without tools." | | | |
| 2 | fold-light | Fold task light has a replaceable light module. | conflict | "The Fold task light LED module is integrated and is not user-replaceable." | | | |
| 3 | halo-light | Halo studio light has serviceable components. | verified | "The Halo studio light has serviceable components: the arm joints and the external power supply can be replaced." | | | |
| 4 | halo-light | Halo studio light has a replaceable bulb. | not_verifiable | none (the bulb is never mentioned) | | | |
| 5 | mini-light | Mini LED light has a replaceable bulb. | conflict | "The Mini LED light bulb cannot be replaced; the LED is sealed inside the housing." | | | |
| 6 | arc-light | Retrieval: "Product arc-light: Arc desk light" | returns the Arc doc only | source is `arc-light_spec_v1.md`, not Fold or Halo | | | |

## Demo mapping

- **Happy path:** Arc. Verified, affordable, so the proposal is allowed.
- **Negative case:** Fold. The local catalog says "replaceable light module" and the lamp is in stock and affordable, but Senso's evidence contradicts the claim, so it's blocked.
- **Missing fact:** Halo with the bulb claim (row 4). Not verifiable, so it's blocked. Note that the app's current claim for Halo is "serviceable components" (row 3), which these docs *do* support. Change the claim for Halo if you want it blocked in the demo.
- **Control:** Mini. It's already rejected by the local catalog, so it doesn't count as the Senso negative case.
- **Senso unavailable:** no data needed. Remove the key or network and the app must show "couldn't check", never verified.

## Reliable means

Every row gives the same verdict and the same passage on all 3 runs.
