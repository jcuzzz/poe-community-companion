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


def _can_edit(user, strategy: Strategy) -> bool:
    return user.is_staff or strategy.author_id == user.id


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
    for variant in variants:
        nodes = variant.atlas_tree.get("nodes") if isinstance(variant.atlas_tree, dict) else None
        if nodes:
            variant.tree_thumb = atlas_render.render_tree_svg(nodes, mode="thumb")
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
        messages.success(request, "Strategy posted. Add variants for budget/endgame tiers.")
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
def variant_tree(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    """Atlas tree viewer (everyone) / editor (author & staff) for one variant.

    Saves happen as POSTs of a JSON node-id list (the editor's hidden field) or
    an imported share link; both are validated server-side before storing.
    """
    import json as _json

    from . import atlas_codec, atlas_data, atlas_render

    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    variant = get_object_or_404(StrategyVariant, pk=pk, strategy=strategy)
    can_edit = _can_edit(request.user, strategy)
    error = None
    attempted = None  # a rejected submission, re-rendered so the edit isn't lost

    if request.method == "POST":
        if not can_edit:
            raise Http404
        if request.POST.get("action") == "import":
            try:
                ids = atlas_codec.decode_atlas_url(request.POST.get("tree_url", ""))
            except ValueError as exc:
                ids, error = None, str(exc)
        else:
            try:
                ids = [int(n) for n in _json.loads(request.POST.get("nodes", "[]"))]
            except (ValueError, TypeError, RecursionError, OverflowError):
                ids, error = None, "Could not read the allocated nodes — try again."
        if ids is not None:
            valid_ids, error = atlas_data.validate_allocation(ids)
            if error is None:
                variant.atlas_tree = {
                    "version": atlas_data.load()["version"],
                    "nodes": valid_ids,
                }
                variant.save(update_fields=["atlas_tree"])
                messages.success(request, f"Atlas tree saved ({len(valid_ids)} points).")
                return redirect("strategy_variant_tree", slug=strategy.slug, pk=variant.pk)
            # Keep only ids the renderer knows so the rejected set still draws.
            attempted = [i for i in ids if i in atlas_data.node_ids()]

    stored = variant.atlas_tree.get("nodes", []) if isinstance(variant.atlas_tree, dict) else []
    allocated = attempted if attempted is not None else stored
    # The stored JSON is admin-editable, so treat it as untrusted: a bad id list
    # must degrade to "no share link", never a 500.
    try:
        share_url = atlas_codec.encode_ggg_url(allocated) if allocated else ""
    except ValueError:
        share_url = ""
    mode = "edit" if can_edit else "view"
    return render(
        request,
        "strategies/variant_tree.html",
        {
            "strategy": strategy,
            "variant": variant,
            "mode": mode,
            "can_edit": can_edit,
            "tree_svg": atlas_render.render_tree_svg(allocated, mode="full"),
            "graph_data": atlas_render.graph_data() if can_edit else None,
            "allocated_json": _json.dumps(allocated),
            "share_url": share_url,
            "tree_error": error,
            "cur": "strategy_list",
        },
    )


@feature_required("strategies")
@login_required
def variant_create(request: HttpRequest, slug: str) -> HttpResponse:
    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    if not _can_edit(request.user, strategy):
        raise Http404
    form = StrategyVariantForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        variant = form.save(commit=False)
        variant.strategy = strategy
        variant.save()
        messages.success(request, f'Variant "{variant.name}" added.')
        return redirect("strategy_detail", slug=strategy.slug)
    return render(
        request,
        "strategies/variant_form.html",
        {"form": form, "strategy": strategy, "is_new": True, "cur": "strategy_list"},
    )


@feature_required("strategies")
@login_required
def variant_edit(request: HttpRequest, slug: str, pk: int) -> HttpResponse:
    qs, _ = _visible(request)
    strategy = get_object_or_404(qs, slug=slug)
    if not _can_edit(request.user, strategy):
        raise Http404
    variant = get_object_or_404(StrategyVariant, pk=pk, strategy=strategy)
    form = StrategyVariantForm(request.POST or None, instance=variant)
    if request.method == "POST":
        if request.POST.get("action") == "delete":
            variant.delete()
            messages.success(request, "Variant removed.")
            return redirect("strategy_detail", slug=strategy.slug)
        if form.is_valid():
            form.save()
            messages.success(request, "Variant updated.")
            return redirect("strategy_detail", slug=strategy.slug)
    return render(
        request,
        "strategies/variant_form.html",
        {"form": form, "strategy": strategy, "variant": variant, "is_new": False, "cur": "strategy_list"},
    )
