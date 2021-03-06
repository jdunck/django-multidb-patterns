import time

from django import forms, http
from django.conf import settings
from django.contrib.auth import models as auth_models
from django.core.cache import cache
from django.core.urlresolvers import reverse
from django.shortcuts import render_to_response, redirect
from django.template import RequestContext, loader

import products.models
import reviews.models


class ReviewForm(forms.Form):
    """
    Simple product review entry form. Reviewer selects a product, an optional
    rating between 1 and 5 and provides a textual review.
    """
    product = forms.ChoiceField()
    rating = forms.ChoiceField(required=False,
            choices=[("", "-")] + [(x, x) for x in range(1, 6)])
    review = forms.CharField()

    _cache_key = "review:prod_choices"

    def __init__(self, *args, **kwargs):
        # The product dropdown has to be initialised from another database (or
        # the cache).
        super(ReviewForm, self).__init__(*args, **kwargs)
        prod_choices = cache.get(self._cache_key)
        if not prod_choices:
            blank = [("", "< Please choose one >")]
            prod_choices = blank + list(products.models.Product.objects. \
                    values_list("id", "name"))
            cache.set(self._cache_key, prod_choices)
        self.fields["product"].choices = prod_choices

    def clean_rating(self):
        value = self.cleaned_data["rating"]
        if value == u"":
            return None
        return value


def add_review(request, product_id=None):
    """
    Submit a review for a product. As a consequence of this, the user will have
    subsequent reads tied to the master reviews database for a set period.
    """
    if request.method == "POST":
        form = ReviewForm(request.POST)
        if form.is_valid():
            data = form.cleaned_data
            user = request.user
            review = reviews.models.Review.objects.create(
                    author_id = user.is_authenticated() and user.id or -1,
                    product_id = data["product"],
                    rating = data["rating"],
                    text = data["review"]
            )
            request.session[settings.MASTER_WRITE_KEY] = time.time()
            return http.HttpResponseRedirect(reverse("show-review",
                    args=[review.id]))
    else:
        if product_id:
            initial = {"product": product_id}
        else:
            initial = None
        form = ReviewForm(initial=initial)
    data = {
            "form": form,
            "title": "Create new review",
            }
    return render_to_response("reviews/new_review.html", data,
            RequestContext(request))

def show_review(request, review_id=None):
    """
    View a review for a product. If no review_id is given, a page for selecting
    the review to show is displayed. If no product_id is given, a page for
    selecting the product is displayed.
    """
    if review_id is None:
        return redirect("product-reviews")
    review_mgr = reviews.models.Review.objects
    if (request.session.get(settings.MASTER_WRITE_KEY, 0) >
            time.time() - settings.WRITE_BIND_TIME):
        # Tie reads to the master reviews database.
        review_mgr = review_mgr.db_manager("reviews")
    try:
        review = review_mgr.get(id=review_id)
    except reviews.models.Review.DoesNotExist:
        return http.HttpResponseNotFound(loader.render_to_string(
                "reviews/missing.html",
                context_instance=RequestContext(request)))
    if review.author_id == -1:
        user = auth_models.AnonymousUser()
    else:
        user = auth_models.User.objects.get(id=review.author_id)
    product = products.models.Product.objects.get(id=review.product_id)
    data = {
            "title": "Reviews",
            "product": product,
            "review": review,
            "reviewer": user,
            }
    return render_to_response("reviews/review.html", data,
            RequestContext(request))

def product_reviews(request, product_id=None):
    """
    Show all review (reviewer + date) for all products in a list.
    """
    review_mgr = reviews.models.Review.objects
    if (request.session.get(settings.MASTER_WRITE_KEY, 0) >
            time.time() - settings.WRITE_BIND_TIME):
        # Tie reads to the master reviews database.
        review_mgr = review_mgr.db_manager("reviews")
    product_list = products.models.Product.objects.order_by("name")
    review_qs = review_mgr.order_by("-created")
    review_dict = {}
    author_ids = [obj.author_id for obj in review_qs]
    users = dict(auth_models.User.objects.filter(id__in=author_ids). \
            values_list("id", "username"))
    users[-1] = "Anonymous"
    for review in review_qs:
        review.reviewer = users[review.author_id]
        review_dict.setdefault(review.product_id, []).append(review)
    for product in product_list:
        product.reviews = review_dict.get(product.id, [])
    data = {
            "title": "All product reviews",
            "products": product_list,
            }
    return render_to_response("reviews/product_reviews.html", data,
            RequestContext(request))

