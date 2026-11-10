from django.contrib import admin

from .models import Article


class ArticleAdmin(admin.ModelAdmin):
    fieldsets = [
        (None, {"fields": ["title"]}),
        ("Advanced options", {"classes": ["collapse"], "fields": ["summary", "slug"]}),
    ]


site = admin.AdminSite(name="admin")
site.register(Article, ArticleAdmin)
