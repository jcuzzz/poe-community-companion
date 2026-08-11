"""Strategy library views. Every view is gated on the "strategies" feature flag."""

from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from tracker.features import feature_required
from tracker.leagues import get_active_league, get_viewing_league

from .forms import StrategyForm, StrategyVariantForm
from .models import Strategy, StrategyVariant, StrategyVote


SCARAB_SLOTS = 5


def _can_edit(user, strategy: Strategy) -> bool:
    return user.is_staff or strategy.author_id == user.id


def _scarab_slots(variant: StrategyVariant) -> list[dict | None]:
    """The variant's scarabs as five device-style slots (``None`` = empty)."""
    from . import scarabs as scarab_catalogue

    names = [str(n) for n in (variant.scarabs or [])][:SCARAB_SLOTS]
    slots: list[dict | None] = [
        {"name": name, "icon": scarab_catalogue.icon_for(name)} for name in names
    ]
    slots += [None] * (SCARAB_SLOTS - len(slots))
    return slots


def _variant_nodes(variant: StrategyVariant) -> list:
    return variant.atlas_tree.get("nodes", []) if isinstance(variant.atlas_tree, dict) else []


def _share_url(allocated) -> str:
    """GGG share link for ``allocated``; "" when the stored ids are unusable.

    The stored JSON is admin-editable, so a bad id list must degrade to "no
    share link", never a 500.
    """
    from . import atlas_codec

    try:
        return atlas_codec.encode_ggg_url(allocated) if allocated else ""
    except ValueError:
        return ""


def _visible(request: HttpRequest):
    """Published strategies in the viewing league (authors/staff see their drafts)."""
    league = get_viewing_league(request)
    qs = Strategy.objects.filter(league=league).select_related("author")
    if request.user.is_staff:
        return qs, league
    from django.db.models import Q

    return qs.filter(Q(is_published=True) | Q(author=request.user)), league


@feature_required("strategies")
@login_required
def strategy_list(request: HttpRequest) -> HttpResponse:
    qs, league = _visible(request)
    tag = request.GET.get("tag", "").strip()
    if tag:
        qs = qs.filter(tags__icontains=tag)
    qs = qs.annotate(vote_count=Count("votes")).order_by("-vote_count", "-updated_at")
    strategies = list(qs)
    voted_ids = set(
        StrategyVote.objects.filter(user=request.user, strategy__in=strategies).values_list(
            "strategy_id", flat=True
        )
    )
    all_tags = sorted({t for s in qs for t in s.tag_list})
    return render(
        request,
        "strategies/strategy_list.html",
        {
            "strategies": strategies,
            "voted_ids": voted_ids,
            "tag": tag,
            "all_tags": all_tags,
            "cur": "strategy_list",
        },
    )


@feature_required("strategies")
@login_required
def strategy_detail(request: HttpRequest, slug: str) -> HttpResponse:
    qs, league = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    from . import atlas_render

    variants = list(strategy.variants.all())
    # Each full tree is ~600KB of inline SVG, so only the initially-active tab
    # is server-rendered; the rest fetch their tree from variant_tree_partial
    # the first time their tab is opened.
    for index, variant in enumerate(variants):
        variant.slots = _scarab_slots(variant)
        variant.extra_scarabs = [str(n) for n in (variant.scarabs or [])][SCARAB_SLOTS:]
        variant.nodes = _variant_nodes(variant)
        variant.tree_svg = (
            atlas_render.render_tree_svg(variant.nodes, mode="full") if index == 0 else None
        )
        variant.share_url = _share_url(variant.nodes)
    return render(
        request,
        "strategies/strategy_detail.html",
        {
            "strategy": strategy,
            "variants": variants,
            "vote_count": strategy.votes.count(),
            "has_voted": strategy.votes.filter(user=request.user).exists(),
            "can_edit": _can_edit(request.user, strategy),
            "cur": "strategy_list",
        },
    )


@feature_required("strategies")
@login_required
def strategy_create(request: HttpRequest) -> HttpResponse:
    league = get_active_league()
    if league is None:
        messages.error(request, "There is no active league yet. Ask an admin to set one.")
        return redirect("strategy_list")
    form = StrategyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        strategy = form.save(commit=False)
        strategy.league = league
        strategy.author = request.user
        strategy.save()
        # Every strategy starts with one variant so the atlas tree / scarab
        # fields are immediately reachable (rename it or add tiers later).
        StrategyVariant.objects.create(strategy=strategy, name="Main")
        messages.success(
            request,
            "Strategy posted. Set the atlas tree on the Main variant, "
            "or add Budget/Endgame tiers.",
        )
        return redirect("strategy_detail", slug=strategy.slug)
    return render(
        request,
        "strategies/strategy_form.html",
        {"form": form, "is_new": True, "cur": "strategy_list"},
    )


@feature_required("strategies")
@login_required
def strategy_edit(request: HttpRequest, slug: str) -> HttpResponse:
    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    if not _can_edit(request.user, strategy):
        raise Http404
    form = StrategyForm(request.POST or None, instance=strategy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Strategy updated.")
        return redirect("strategy_detail", slug=strategy.slug)
    return render(
        request,
        "strategies/strategy_form.html",
        {"form": form, "is_new": False, "strategy": strategy, "cur": "strategy_list"},
    )


@feature_required("strategies")
@login_required
def strategy_delete(request: HttpRequest, slug: str) -> HttpResponse:
    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    if not _can_edit(request.user, strategy):
        raise Http404
    if request.method == "POST":
        strategy.delete()
        messages.success(request, "Strategy deleted.")
        return redirect("strategy_list")
    return redirect("strategy_detail", slug=slug)


@feature_required("strategies")
@login_required
def strategy_vote(request: HttpRequest, slug: str) -> HttpResponse:
    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    if request.method == "POST":
        vote, created = StrategyVote.objects.get_or_create(strategy=strategy, user=request.user)
        if not created:
            vote.delete()
    if request.POST.get("next") == "list":
        return redirect("strategy_list")
    return redirect("strategy_detail", slug=slug)


@feature_required("strategies")
@login_required
def variant_tree_partial(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    """Read-only tree viewer for one variant, as an HTML fragment.

    The strategy detail page fetches this the first time a variant tab is
    opened, so only one ~600KB tree is ever in the initial document.
    """
    from . import atlas_render

    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    variant = get_object_or_404(StrategyVariant, pk=pk, strategy=strategy)
    nodes = _variant_nodes(variant)
    return render(
        request,
        "strategies/_variant_tree_view.html",
        {
            "strategy": strategy,
            "variant": variant,
            "nodes": nodes,
            "tree_svg": atlas_render.render_tree_svg(nodes, mode="full"),
            "share_url": _share_url(nodes),
        },
    )


@feature_required("strategies")
@login_required
def variant_create(request: HttpRequest, slug: str) -> HttpResponse:
    """Create an empty variant and drop the author straight into the editor."""
    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    if not _can_edit(request.user, strategy):
        raise Http404
    count = strategy.variants.count()
    variant = StrategyVariant.objects.create(
        strategy=strategy,
        name="Main" if count == 0 else f"Variant {count + 1}",
        order=count,
    )
    messages.success(request, f'Variant "{variant.name}" added — set it up below.')
    return redirect("strategy_variant_edit", slug=strategy.slug, pk=variant.pk)


@feature_required("strategies")
@login_required
def variant_edit(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    """The one variant editor: fields + scarab picker + atlas tree, one Save.

    A single POST carries the ``StrategyVariantForm`` fields and the tree's
    hidden node-id JSON; both are validated before anything is written, and a
    rejection re-renders with the attempted allocation and the typed-in field
    values intact. ``action=import`` is a round-trip that only loads a shared
    tree into the editor — the user still has to Save.
    """
    import json as _json

    from . import atlas_codec, atlas_data, atlas_render, influences

    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    if not _can_edit(request.user, strategy):
        # Their read view is the strategy page now.
        return redirect("strategy_detail", slug=strategy.slug)
    variant = get_object_or_404(StrategyVariant, pk=pk, strategy=strategy)

    form = StrategyVariantForm(instance=variant)
    error = None
    attempted = None  # a rejected/imported node set, re-rendered so it isn't lost

    if request.method == "POST":
        action = request.POST.get("action", "save")
        if action == "delete":
            variant.delete()
            messages.success(request, "Variant removed.")
            return redirect("strategy_detail", slug=strategy.slug)

        # Bind the form either way so typed-in values survive an import
        # round-trip or a tree rejection.
        form = StrategyVariantForm(request.POST, instance=variant)
        if action == "import":
            form.is_valid()  # populate cleaned_data / show field errors, don't save
            try:
                ids = atlas_codec.decode_atlas_url(request.POST.get("tree_url", ""))
            except ValueError as exc:
                ids, error = None, str(exc)
            if ids is not None:
                valid_ids, error = atlas_data.validate_allocation(ids)
                if error is None:
                    attempted = valid_ids
                    messages.info(
                        request,
                        f"Imported {len(valid_ids)} points — press Save to keep them.",
                    )
                else:
                    attempted = [i for i in ids if i in atlas_data.node_ids()]
        else:
            try:
                ids = [int(n) for n in _json.loads(request.POST.get("nodes", "[]"))]
            except (ValueError, TypeError, RecursionError, OverflowError):
                ids, error = None, "Could not read the allocated nodes — try again."
            valid_ids = None
            if ids is not None:
                valid_ids, error = atlas_data.validate_allocation(ids)
                if error is not None:
                    # Keep only ids the renderer knows so the rejected set draws.
                    attempted = [i for i in ids if i in atlas_data.node_ids()]
            if error is None and form.is_valid():
                saved = form.save(commit=False)
                saved.atlas_tree = (
                    {"version": atlas_data.load()["version"], "nodes": valid_ids}
                    if valid_ids
                    else {}
                )
                saved.save()
                messages.success(
                    request, f'Saved "{saved.name}" ({len(valid_ids or [])} atlas points).'
                )
                return redirect("strategy_detail", slug=strategy.slug)

    allocated = attempted if attempted is not None else _variant_nodes(variant)
    return render(
        request,
        "strategies/variant_editor.html",
        {
            "strategy": strategy,
            "variant": variant,
            "form": form,
            "mode": "edit",
            "tree_svg": atlas_render.render_tree_svg(allocated, mode="full"),
            "graph_data": atlas_render.graph_data(),
            "allocated_json": _json.dumps(allocated),
            "share_url": _share_url(allocated),
            "influence_options": influences.options(),
            "selected_influence": (
                form["device_influence"].value() or "" if form.is_bound else variant.device_influence
            ),
            "tree_error": error,
            "cur": "strategy_list",
        },
    )
