from django.db import models


class Article(models.Model):
    title = models.CharField(max_length=100)
    summary = models.TextField(blank=True)
    slug = models.SlugField(blank=True)
