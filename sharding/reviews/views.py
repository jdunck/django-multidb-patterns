from django import forms, http
from django.contrib.auth import models as auth_models
from django.core.cache import cache
from django.core.urlresolvers import reverse
from django.shortcuts import render_to_response, redirect
from django.template import RequestContext, loader

import products.models
import reviews.models
from reviews import router


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
    Submit a review for a product.
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
    alias = "reviews-%d" % reviews.models.get_db_for_id(review_id)
    try:
        review = reviews.models.Review.objects.using(alias).get(id=review_id)
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
    product_list = products.models.Product.objects.order_by("name")
    review_qs = reviews.models.Review.objects.order_by("-created")
    review_dict = {}
    users = {-1: "Anonymous"}
    for db_alias in router.alias_iter():
        current_qs = review_qs.using(db_alias)
        review_ids = [obj.author_id for obj in current_qs]
        users.update(dict(auth_models.User.objects.filter(id__in=review_ids).
                values_list("id", "username")))
        for review in current_qs:
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

