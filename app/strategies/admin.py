from django.contrib import admin

from .models import Strategy, StrategyVariant, StrategyVote


class StrategyVariantInline(admin.StackedInline):
    model = StrategyVariant
    extra = 0


@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ["title", "league", "author", "kind", "is_published", "updated_at"]
    list_filter = ["league", "kind", "is_published"]
    search_fields = ["title", "tags", "body"]
    prepopulated_fields = {"slug": ["title"]}
    inlines = [StrategyVariantInline]


@admin.register(StrategyVote)
class StrategyVoteAdmin(admin.ModelAdmin):
    list_display = ["strategy", "user", "created_at"]
