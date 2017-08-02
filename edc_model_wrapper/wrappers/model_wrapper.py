from django.apps import apps as django_apps
from django.urls.exceptions import NoReverseMatch
from urllib import parse

from ..parsers import NextUrlParser, Keywords
from .fields import Fields


class ModelWrapperError(Exception):
    pass


class ModelWrapperModelError(Exception):
    pass


class ModelWrapperObjectAlreadyWrapped(Exception):
    pass


class ModelWrapperInvalidProperty(Exception):
    pass


class ModelWrapperNoReverseMatch(Exception):
    pass


class ModelWrapper:

    """A wrapper for model instances or classes.

    Keyword args:
        model_obj: An instance of a model class
        model: name of model class that wrapper accepts,
            if specified. (Default: None)

    Set attrs, flatten relations, adds admin and next urls,
    onto a model object to be used in views and templates.

    Common model and url attrs are added onto self so you can avoid
    accessing the model instance directly.
    For example:
        instead of this:
            model_wrapper.object.created  # not allowed in templates
            model_wrapper.wrapped_object.created
            model_wrapper.<my model name>.created
        this:
            model_wrapper.created

    * object: The wrapped model instance. Will include URLs
        and any other attrs that the wrapper is configured to add.
    * """

    fields_cls = Fields
    keywords_cls = Keywords
    next_url_parser_cls = NextUrlParser

    model = None  # class or label_lower
    next_url_name = None  # should include namespace:url_name
    next_url_attrs = []
    querystring_attrs = []

    def __init__(self, model_obj=None, model=None, next_url_name=None,
                 next_url_attrs=None, querystring_attrs=None, **kwargs):

        self.object = model_obj
        self.model_name = model_obj._meta.object_name.lower().replace(' ', '_')
        self.model = self.model or self._get_model_cls_or_raise(
            model_obj, model)

        fields_obj = self.fields_cls(model_obj=self.object)
        self.fields = fields_obj.get_field_values_as_strings

        self.querystring_attrs = querystring_attrs or self.querystring_attrs
        self.next_url_parser = self.next_url_parser_cls(
            url_name=next_url_name or self.next_url_name,
            url_args=next_url_attrs or self.next_url_attrs)

        # wrap me with kwargs
        for attr, value in kwargs.items():
            try:
                setattr(self, attr, value)
            except AttributeError:
                # skip if attr cannot be overwritten
                pass

        # wrap me with field attrs
        for name, value in self.fields(wrapper=self):
            try:
                setattr(self, name, value)
            except AttributeError:
                # skip if attr cannot be overwritten
                pass

        # wrap me with next url and it's required attrs
        self.next_url = self.next_url_parser.querystring(
            objects=[self, self.object], **kwargs)

        # wrap me with admin urls
        self.get_absolute_url = self.object.get_absolute_url
        # see also UrlMixin.admin_url_name
        self.admin_url_name = f'{self.object.admin_url_name}'

        # wrap with an additional querystring for extra values needed
        # in the view
        self.keywords = self.keywords_cls(
            objects=[self], attrs=self.querystring_attrs, **kwargs)
        self.querystring = parse.urlencode(self.keywords, encoding='utf-8')

        # flag as wrapped and disable save
        self.object.wrapped = True
        self.object.save = None
        self.add_extra_attributes_after()

        # reverse admin url (must be registered w/ the site admin)
        self.href = f'{self.get_absolute_url()}?next={self.next_url}&{self.querystring}'

    def reverse(self):
        """Returns the reversed next_url_name or None.
        """
        try:
            next_url = self.next_url_parser.reverse(model_wrapper=self)
        except NoReverseMatch as e:
            raise ModelWrapperNoReverseMatch(
                f'next_url_name={self.next_url_name}. Got {e}')
        return next_url

    def add_extra_attributes_after(self, **kwargs):
        """Called after the model is wrapped."""
        pass

    def __repr__(self):
        return f'{self.__class__.__name__}({self.object} id={self.object.id})'

    def __bool__(self):
        return True if self.object.id else False

    @property
    def _meta(self):
        return self.object._meta

    def _get_model_cls_or_raise(self, model_obj, model=None):
        """Returns the given model, as a class, or raises an exception.

        Validates that the model instance (model_obj) is an instance
        of model and the model instance is not a wrapped model instance.
        """
        if not model:
            model_cls = model_obj.__class__
        else:
            try:
                model_cls = django_apps.get_model(*model.split('.'))
            except AttributeError:
                model_cls = model
            except ValueError as e:
                raise ModelWrapperModelError(f'{e}. Got model={model}.')
            if not isinstance(model_obj, model_cls):
                raise ModelWrapperModelError(
                    f'Expected an instance of {model}. Got model_obj={model_obj}')
        # assert model obj can only be wrapped once.
        try:
            assert not model_obj.wrapped
        except AttributeError:
            pass
        except AssertionError:
            raise ModelWrapperObjectAlreadyWrapped(
                f'Model is already wrapped. Got {model_obj}')
        return model_cls
