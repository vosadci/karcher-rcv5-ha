# Demo map fixture (for card screenshots)

Generates a synthetic 5-room apartment (no real device data) for screenshotting
`www/karcher-vacuum-card.js` — e.g. for the project README.

## 1. Generate the fixture

```bash
PYTHONPATH=. ~/.venvs/ha-dev/bin/python tests/tools/generate_demo_map_fixture.py
```

Writes to `demo_fixture/` (git-ignored):
- `demo_map.png` — floor-plan image
- `demo_attributes.json` — vacuum entity attributes (`room_map`, `map_image_size`,
  `robot_px`, `charger_px`, `cur_path_px`, `map_legend`)

Use `--out-dir <path>` to write elsewhere.

## 2. Set up a local HA instance

Don't use Developer Tools → States on a real `karcher_home_robots` entity —
the coordinator's next poll/push overwrites any manual override within
seconds. Instead use the static dev-only `karcher_demo_card` integration in
`tests/tools/demo_card_integration/`: it has no coordinator and no update
loop, so its state never resets.

1. Copy `tests/tools/demo_card_integration/custom_components/karcher_demo_card`
   into your HA dev instance's `<config>/custom_components/`.
2. Add to `<config>/configuration.yaml` (point `fixture_dir` at the folder
   from step 1, e.g. copy `demo_fixture/` into `<config>/demo_fixture/`):
   ```yaml
   vacuum:
     - platform: karcher_demo_card
       fixture_dir: /config/demo_fixture
   image:
     - platform: karcher_demo_card
       fixture_dir: /config/demo_fixture
   sensor:
     - platform: karcher_demo_card
   ```
3. Restart HA. `vacuum.demo_card`, `image.demo_card_map`, and
   `sensor.demo_card_battery` now exist, holding the fixture data forever.
4. Register the card resource (Settings → Dashboards → Resources →
   `/local/karcher-vacuum-card.js`) and add a `custom:karcher-vacuum-card`
   card with `entity: vacuum.demo_card` and `map_entity: image.demo_card_map`
   (the card auto-derives `battery_entity: sensor.demo_card_battery` from
   the vacuum entity id).

## 3. Screenshot

Open the dashboard in a real browser (not the vitest/happy-dom test suite —
canvas painting isn't supported there) and screenshot the card.
