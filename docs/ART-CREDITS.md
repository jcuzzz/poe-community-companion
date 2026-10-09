# Art credits

This project uses Path of Exile game art. PoE and all related imagery are the
property of **Grinding Gear Games**.

## Item / currency icons
Hotlinked at runtime from GGG's own CDN (`web.poecdn.com`) — not redistributed in
this repo. Used for achievement icons (Divine Orb, Mirror of Kalandra, Hinekora's
Lock, Ralakesh's Impatience, …). See `Achievement.art_url`.

## Class / ascendancy portraits
Bundled under `app/static/img/classes/` (19 PoE 1 ascendancy banners + the 7 base-class
avatar headshots: marauder, ranger, witch, duelist, templar, shadow, scion — used for
characters who haven't ascended yet). Sourced from the **Path of Exile Wiki on Fandom**
(`pathofexile.fandom.com`), whose content is licensed **CC-BY-NC-SA**. Attribution: Path
of Exile Wiki contributors; artwork © Grinding Gear Games. Note the base-class avatars are
small square headshots while the ascendancy art is a wide banner — the UI crops them
differently (see `portrait_is_avatar`).

> **License note:** the bundled portraits are CC-BY-NC-SA (non-commercial,
> share-alike), which differs from the MIT license covering the code. Keep the art in a
> non-commercial context and retain this attribution. If you need a fully MIT-clean
> fork, remove `app/static/img/classes/`.

This product isn't affiliated with or endorsed by Grinding Gear Games in any way.
