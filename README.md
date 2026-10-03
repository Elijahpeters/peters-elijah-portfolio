# Peters Elijah Temidayo — Engineering Portfolio

**Live site:** [peterselijah.name.ng](https://peterselijah.name.ng) ·
**SkyETA:** [peterselijah.name.ng/skyeta](https://peterselijah.name.ng/skyeta) ·
[LinkedIn](https://www.linkedin.com/in/elijahpeters01) ·
[CV](public/assets/Peters-Elijah-CV.pdf)

I am an Electrical & Electronics Engineer (B.Eng, Second Class Upper, Olabisi
Onabanjo University) working across circuit design, PCB layout and applied
machine learning. This repository holds my portfolio site and SkyETA, the
flight-reliability product that runs inside it.

Each project below answers the same six questions, so you can judge the
thinking as well as the build.

| Project | One-line summary | Headline evidence |
| --- | --- | --- |
| [SkyETA](#skyeta--flight-search-with-honest-delay-evidence) | Flight comparison that shows how reliable a flight has been | 5.15M U.S. flight records; held-out test reported once |
| [AuraPass](#aurapass--offline-exam-access-control) | Offline face-verified exam access | 0 false grants in 5,000 impostor attempts |
| [Incubator carrier and circuit studies](#incubator-carrier-board-and-circuit-studies) | A KiCad PCB and five circuit studies | 0 ERC/DRC errors; not yet bench-tested |

---

## SkyETA — flight search with honest delay evidence

**1. What problem does it solve?**
Travellers compare flights on price and time, but cannot see how likely a
flight is to arrive late.

**2. Why does it matter?**
About 1 in 5 U.S. domestic flights arrived 15 or more minutes late in the 2025
data (22%). A late arrival can mean a missed connection or a lost day, so
reliability belongs beside the fare when choosing a flight.

**3. What did I build?**
Official flight records → Python, pandas and LightGBM → calibrated delay
probability → a TypeScript web app on Cloudflare Workers.

- A delay model trained on U.S. Bureau of Transportation Statistics records,
  using only information known before departure.
- A worldwide flight search that shows provider fares, schedules and baggage,
  with route-matched delay history where real records exist.
- The model runs in the visitor's browser, so no API key is exposed.

**4. What did I find?**

- **Schedule data alone is a weak predictor.** The model scored ROC-AUC 0.64 on
  validation and 0.61 on the untouched December test month. It ranks risk
  better than chance, but it cannot call individual flights.
- **Delay rates shift by season.** December ran at 26.7% late against 20.5% in
  the validation months, and calibration error rose from 0.006 to 0.068.
- **A yes/no label would mislead.** At the usual 50% cut-off the model flags no
  flights at all, so the app shows a probability instead of "on time/delayed".
- **A second country gave the same picture.** On 643,404 Brazilian schedule
  rows matched to outcomes, the 15-minute model scored ROC-AUC 0.64 and did not
  beat a constant-rate baseline on Brier score.

**5. What should happen next?**

- Bring pre-departure weather into the served model. The pipeline for it exists
  (NOAA observations up to three hours before departure) but is not yet live.
- Recalibrate by season so winter probabilities are not understated.
- Keep the Brazilian model out of production until it passes a forward-in-time
  test. My own gate review blocked it.

**6. What assumptions and trade-offs did I make?**

- **I split the data by time, not at random.** Training on January–September
  and testing on December gives lower scores than a random split, but it is how
  the model would really be used: predicting flights that have not happened.
- **I chose honesty over coverage.** A route with fewer than five completed
  flights on record shows no percentage. A blank is less harmful than an
  invented number a traveller might rely on.
- **I kept the trained model and the observed history separate.** They answer
  different questions, so the app labels each one and never blends them.
- **I used the test month once.** All tuning and calibration used validation
  data, so the reported test result is not flattered by repeated tries.

Code: [`app/skyeta`](app/skyeta) (interface), [`app/api/skyeta`](app/api/skyeta)
(server), [`skyeta-ml`](skyeta-ml) (model pipeline) ·
[Model card](public/assets/skyeta-model-card.json) ·
[Brazil gate review](skyeta-ml/global/ANAC_2023_ANNUAL_MODEL_GATE_REVIEW.md)

---

## AuraPass — offline exam access control

**1. What problem does it solve?**
Confirm that the person entering an exam hall is the registered student, is
eligible for that course, and has not already entered.

**2. Why does it matter?**
Exam impersonation undermines the result for every candidate. The check also
has to work where there is no reliable internet, so it runs fully offline.

**3. What did I build?**
Course-form data and face samples → Python, OpenCV and SQLite → access
decision → simulated gate in Proteus over UDP/serial.

The system checks identity, course eligibility, repeat entry and hall capacity
before it reserves a seat and opens the gate.

**4. What did I find?**

- **No impostor was admitted.** In 5,000 attempts by non-enrolled faces, 0 were
  granted access.
- **Image quality is the main failure mode.** 1,207 attempts (24%) were
  rejected for quality before any matching took place.
- **Blur is the hardest condition.** 383 of 500 blurred attempts were
  quality-rejected, against 51 of 500 for unaltered images.

**5. What should happen next?**

- Measure how often genuine enrolled students are wrongly turned away.
- Test with live camera capture in real hall lighting.
- Replace the simulated gate with physical hardware.

**6. What assumptions and trade-offs did I make?**

- **I prioritised stopping impostors over convenience.** Admitting the wrong
  person compromises an exam, while a wrongly rejected student can be checked
  again by a person. The system therefore rejects when it is unsure.
- **The test measures false grants only.** It used 500 public LFW faces in 10
  variants each. It does not measure overall biometric accuracy, and I do not
  claim one.
- **Offline first.** Records stay in a local SQLite database. That removes the
  network dependency, but each installation holds only its own records.

Code: [github.com/Elijahpeters/AuraPass](https://github.com/Elijahpeters/AuraPass) ·
[Evaluation summary](public/assets/aurapass-negative-face-evaluation-summary.csv) ·
[Case study](https://peterselijah.name.ng/projects/aurapass)

---

## Incubator carrier board and circuit studies

**1. What problem does it solve?**
An Arduino Mega incubator controller needs its sensor connections, relay
control signals and status LEDs brought into one organised interface.

**2. Why does it matter?**
A single board with defined terminals is easier to assemble, inspect and
service than point-to-point wiring, and its layout can be checked before
anything is built.

**3. What did I build?**
Schematic → placement and routing → ERC/DRC and pin-map checks, all in KiCad.

- A 96 × 76 mm two-layer carrier board (Rev C).
- Five circuit studies: an Antoniou GIC, a KHN state-variable filter, an
  instrumentation amplifier, a PFD with charge pump, and a boost converter.

**4. What did I find?**

- **The board passes its design checks.** 0 ERC errors, 0 DRC violations, 0
  unconnected pads and 71 matching pin assignments.
- **One circuit study has a real fault.** The KHN filter has a feedback-sign
  problem. I documented it instead of hiding it.
- **Separate current paths need separate widths.** Signal traces are 0.30 mm;
  the relay coil supply and return are 1.50 mm and 1.20 mm.

**5. What should happen next?**

- Fabricate the board and bench-test it with the actual relay module.
- Confirm connector fit with the purchased parts.
- Correct and re-simulate the KHN filter.

**6. What assumptions and trade-offs did I make?**

- **Clean checks are not proof that the board works.** ERC and DRC confirm the
  design rules, not thermal behaviour, safety or function. The site says "not
  bench-tested" wherever that applies.
- **Trace widths are design choices.** I have not measured their current
  capacity.
- **The images are KiCad renders.** No photograph of assembled hardware exists
  yet, and the site labels them as renders.

Case studies: [PCB](https://peterselijah.name.ng/projects/incubator-carrier) ·
[Circuits](https://peterselijah.name.ng/projects/circuits)

---

## About this repository

- **Stack:** React 19, TypeScript and vinext, deployed as a Cloudflare Worker
  with a D1 database. Python, pandas, scikit-learn and LightGBM for the model.
- **Tests:** 203 automated checks cover the pages, flight providers, payments
  and model logic.
- **Run it locally** (Node.js 22.13 or newer):

  ```bash
  npm install
  npm run dev
  ```

Setup, API keys, deployment and privacy details are in
[docs/OPERATIONS.md](docs/OPERATIONS.md).

## Contact

peterselijah11@gmail.com · [LinkedIn](https://www.linkedin.com/in/elijahpeters01) ·
[GitHub](https://github.com/Elijahpeters)

© 2026 Peters Elijah Temidayo. All rights reserved.
