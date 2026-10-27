from django import forms


class CaptureReviewForm(forms.Form):
    name = forms.CharField(max_length=200, label='Element name')
    description = forms.CharField(required=False, widget=forms.Textarea, label='Description')
