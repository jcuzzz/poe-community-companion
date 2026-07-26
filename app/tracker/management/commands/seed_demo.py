"""Seed a rich DEMO dataset for local UI work (never for production).

Populates players, a full achievement set, varied submissions (so different players
win different medals and the leaderboard/matrix look realistic), plus roster
character snapshots. Idempotent-ish and guarded: refuses to run unless DEBUG is on
or --force is passed. Intended for the Playwright visual-iteration loop.
"""

from __future__ import annotations

import base64
import random
import zlib
from datetime import timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from tracker import scoring
from tracker.models import (
    Achievement,
    CharacterSnapshot,
    League,
    MemberProfile,
    Submission,
    User,
)

PLAYERS = [
    ("jcuz", "Jcuz", "Deadeye", 96),
    ("bob", "Bob", "Necromancer", 94),
    ("carol", "Carol", "Juggernaut", 92),
    ("dave", "Dave", "Occultist", 95),
    ("erin", "Erin", "Slayer", 90),
]

# Base-class for each demo ascendancy (used only in the synthetic PoB XML).
_BASE_CLASS = {
    "Deadeye": "Ranger", "Necromancer": "Witch", "Juggernaut": "Marauder",
    "Occultist": "Witch", "Slayer": "Duelist",
}

# A representative main skill + gear per ascendancy, so each demo character's
# detail page looks distinct.
_BUILD_FLAVOUR = {
    "Deadeye": ("Tornado Shot", "Imperial Bow", "Windripper"),
    "Necromancer": ("Raise Spectre", "Convoking Wand", "Femurs of the Saints"),
    "Juggernaut": ("Boneshatter", "Gavel", "The Brass Dome"),
    "Occultist": ("Blight", "Profane Wand", "Cane of Kulemak"),
    "Slayer": ("Lightning Strike", "Paradoxica", "Starforge"),
}


def _demo_tree_nodes(rng, count: int = 110) -> str:
    """A connected blob of REAL passive-tree node ids (BFS from a random start)
    so the demo character page renders a believable allocated tree."""
    import collections
    from tracker.tree_render import _tree

    data = _tree()
    nodes = data.get("n")
    if not nodes:
        return ""
    adj = collections.defaultdict(set)
    for a, b in data.get("e", []):
        adj[a].add(b)
        adj[b].add(a)
    start = rng.choice(list(nodes))
    seen = {start}
    q = collections.deque([start])
    while q and len(seen) < count:
        cur = q.popleft()
        for nb in adj[cur]:
            if nb not in seen:
                seen.add(nb)
                q.append(nb)
    return ",".join(seen)


def _demo_pob_code(rng, ascendancy: str, class_name: str, level: int) -> str:
    """Build a small but valid PoB export code so the character-detail page and
    parser have real data to work with in the demo. Not a real game build."""
    main_skill, weapon_base, notable = _BUILD_FLAVOUR.get(
        ascendancy, ("Spark", "Wand", "Tabula Rasa")
    )
    life = 3800 + level * 12 + rng.randint(-200, 400)
    es = rng.choice([0, 0, 900, 1500, 2400])
    dps = rng.randint(9, 34) * 100_000
    ehp = int((life + es) * rng.uniform(3.5, 6.0))
    res = [rng.choice([75, 76, 78]) for _ in range(3)]
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<PathOfBuilding>
  <Build level="{level}" targetVersion="3_0" className="{class_name}" ascendClassName="{ascendancy}" mainSocketGroup="1">
    <PlayerStat stat="Life" value="{life}"/>
    <PlayerStat stat="EnergyShield" value="{es}"/>
    <PlayerStat stat="Mana" value="{rng.randint(400, 900)}"/>
    <PlayerStat stat="TotalEHP" value="{ehp}"/>
    <PlayerStat stat="Armour" value="{rng.randint(2000, 12000)}"/>
    <PlayerStat stat="Evasion" value="{rng.randint(1500, 9000)}"/>
    <PlayerStat stat="TotalDPS" value="{dps}"/>
    <PlayerStat stat="Speed" value="{rng.uniform(2.5, 6.5):.2f}"/>
    <PlayerStat stat="CritChance" value="{rng.choice([6, 42, 78, 91])}"/>
    <PlayerStat stat="CritMultiplier" value="{rng.uniform(1.5, 4.2):.2f}"/>
    <PlayerStat stat="FireResist" value="{res[0]}"/>
    <PlayerStat stat="ColdResist" value="{res[1]}"/>
    <PlayerStat stat="LightningResist" value="{res[2]}"/>
    <PlayerStat stat="ChaosResist" value="{rng.randint(-30, 40)}"/>
    <PlayerStat stat="SpellSuppressionChance" value="{rng.choice([0, 30, 100])}"/>
    <PlayerStat stat="BlockChance" value="{rng.choice([0, 24, 43])}"/>
    <PlayerStat stat="Str" value="{rng.randint(90, 260)}"/>
    <PlayerStat stat="Dex" value="{rng.randint(90, 340)}"/>
    <PlayerStat stat="Int" value="{rng.randint(90, 360)}"/>
  </Build>
  <Skills>
    <SkillSet id="1">
      <Skill mainActiveSkill="1">
        <Gem nameSpec="{main_skill}" level="21" quality="20" skillId="{main_skill.replace(' ', '')}"/>
        <Gem nameSpec="Increased Critical Strikes Support" level="20" quality="20" skillId="SupportIncreasedCriticalStrikes"/>
        <Gem nameSpec="Elemental Damage with Attacks Support" level="20" quality="0" skillId="SupportElementalDamage"/>
        <Gem nameSpec="Added Cold Damage Support" level="20" quality="0" skillId="SupportColdDamage"/>
      </Skill>
      <Skill>
        <Gem nameSpec="Herald of Ice" level="20" quality="0" skillId="HeraldOfIce"/>
        <Gem nameSpec="Summon Ice Golem" level="20" quality="0" skillId="SummonIceGolem"/>
      </Skill>
      <Skill>
        <Gem nameSpec="Grace" level="20" quality="0" skillId="Grace"/>
        <Gem nameSpec="Enlighten Support" level="4" quality="0" skillId="SupportEnlighten"/>
      </Skill>
    </SkillSet>
  </Skills>
  <Tree>
    <Spec treeVersion="3_25" nodes="{_demo_tree_nodes(rng, rng.randint(95, 118))}">
      <URL>https://www.pathofexile.com/passive-skill-tree/AAAABgMADemo</URL>
    </Spec>
  </Tree>
  <Items activeItemSet="1">
    <Item id="1">Rarity: RARE
Storm Fang
{weapon_base}</Item>
    <Item id="2">Rarity: UNIQUE
{notable}
Astral Plate</Item>
    <Item id="3">Rarity: RARE
Corpse Veil
Hubris Circlet</Item>
    <Item id="4">Rarity: RARE
Gale Grip
Fingerless Silk Gloves</Item>
    <Item id="5">Rarity: RARE
Dread Trail
Two-Toned Boots</Item>
    <Item id="6">Rarity: RARE
Onslaught Collar
Onyx Amulet</Item>
    <Item id="7">Rarity: RARE
Torment Coil
Vermillion Ring</Item>
    <Item id="8">Rarity: RARE
Corruption Loop
Amethyst Ring</Item>
    <Item id="9">Rarity: RARE
Behemoth Bind
Stygian Vise</Item>
    <ItemSet id="1">
      <Slot name="Weapon 1" itemId="1"/>
      <Slot name="Body Armour" itemId="2"/>
      <Slot name="Helmet" itemId="3"/>
      <Slot name="Gloves" itemId="4"/>
      <Slot name="Boots" itemId="5"/>
      <Slot name="Amulet" itemId="6"/>
      <Slot name="Ring 1" itemId="7"/>
      <Slot name="Ring 2" itemId="8"/>
      <Slot name="Belt" itemId="9"/>
    </ItemSet>
  </Items>
</PathOfBuilding>"""
    compressed = zlib.compress(xml.encode("utf-8"))
    return base64.urlsafe_b64encode(compressed).decode("ascii")


class Command(BaseCommand):
    help = "Seed a rich demo dataset for local UI development (DEBUG only)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="Allow running with DEBUG off.")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError("Refusing to seed demo data with DEBUG off (use --force to override).")

        league = League.get_active()
        if league is None:
            league = League.objects.create(name="Demo League", slug="demo-league", is_active=True)
        # Deterministic randomness (Math.random-style seeding is fine in app code).
        rng = random.Random(42)

        call_command("seed_achievements", league_slug=league.slug)
        achievements = list(Achievement.objects.filter(league=league, active=True))

        users = []
        for username, display, ascendancy, level in PLAYERS:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"display_name": display, "is_player": True, "banner_hue": rng.randint(0, 360)},
            )
            if created:
                user.set_password("correct-horse-battery-42")
                user.save()
            users.append((user, ascendancy, level))
            profile, _ = MemberProfile.objects.get_or_create(user=user)
            profile.show_on_roster = True
            profile.account_name = f"{display}#{1000 + rng.randint(0, 8999)}"
            profile.save()
            CharacterSnapshot.objects.update_or_create(
                user=user,
                league=league,
                defaults={
                    "character_name": f"{display}bot",
                    "class_name": ascendancy,
                    "ascendancy": ascendancy,
                    "level": level,
                    "league_text": league.name,
                    "source": CharacterSnapshot.Source.POB,
                    "raw": _demo_pob_code(
                        rng, ascendancy, _BASE_CLASS.get(ascendancy, "Scion"), level
                    ),
                },
            )

        # Varied submissions: not everyone does every achievement, and stats differ so
        # firsts / lowest-played / fewest-kills / lowest-level spread across players.
        base = timezone.now() - timedelta(days=8)
        for ach in achievements:
            entrants = rng.sample(users, k=rng.randint(1, len(users)))
            for i, (user, _asc, level) in enumerate(entrants):
                if Submission.objects.filter(user=user, achievement=ach).exists():
                    continue
                Submission.objects.create(
                    user=user,
                    league=league,
                    achievement=ach,
                    status=Submission.Status.APPROVED,
                    reviewed_by=user,
                    reviewed_at=timezone.now(),
                    obtained_at=base + timedelta(hours=rng.randint(1, 120)),
                    character_level=level + rng.randint(-6, 4),
                    played_seconds=rng.randint(4, 60) * 3600,
                    kill_count=rng.randint(2000, 40000),
                )

        awards = scoring.recalculate(league=league)
        self.stdout.write(
            self.style.SUCCESS(
                f"Demo seeded: {len(users)} players, {len(achievements)} achievements, "
                f"{Submission.objects.filter(league=league).count()} submissions, {awards} awards."
            )
        )
