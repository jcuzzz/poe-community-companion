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

> **Open-source note:** the bundled portraits are CC-BY-NC-SA (non-commercial,
> share-alike). If this project is published as open source, keep the art in a clearly
> non-commercial context, retain this attribution, and consider making the portrait
> bundle an optional download rather than shipping it in the code repo, to avoid a
> license mismatch with the code's own license.
