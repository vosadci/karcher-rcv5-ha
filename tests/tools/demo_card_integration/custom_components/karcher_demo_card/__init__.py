# SPDX-License-Identifier: MIT
"""Dev-only integration: a static vacuum + image entity for card screenshots.

Not part of the karcher_home_robots package — never ship this. It exists so
Developer Tools -> States overrides on a *real* device entity stop getting
reset by the integration's coordinator on the next poll/push. These entities
have no coordinator and no update loop, so once loaded they hold their state
forever.

Setup is via YAML platform config only (see README_demo_map_fixture.md):

    vacuum:
      - platform: karcher_demo_card
        fixture_dir: /config/demo_fixture
    image:
      - platform: karcher_demo_card
        fixture_dir: /config/demo_fixture
"""
