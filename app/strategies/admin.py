from django.contrib import admin

from .models import Strategy, StrategyVariant, StrategyVote, Tag


class StrategyVariantInline(admin.StackedInline):
    model = StrategyVariant
    extra = 0


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ["title", "league", "author", "kind", "is_published", "updated_at"]
    list_filter = ["league", "kind", "is_published"]
    search_fields = ["title", "tags__name", "body"]
    prepopulated_fields = {"slug": ["title"]}
    filter_horizontal = ["tags"]
    inlines = [StrategyVariantInline]


@admin.register(StrategyVote)
class StrategyVoteAdmin(admin.ModelAdmin):
    list_display = ["strategy", "user", "created_at"]


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ["name", "slug"]
    search_fields = ["name"]
