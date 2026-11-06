from django import forms
from django.utils import timezone

from .models import Intervention


class InterventionForm(forms.ModelForm):
    """Record or update the action taken after reviewing a score (FR012, FR013).

    An open action's follow-up date cannot be set in the past: it would count as
    overdue the moment it was saved. An existing open action whose date has since
    passed can still be edited (for example to add notes or mark it completed)
    without changing that date.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"
        self.fields["follow_up_date"].widget.attrs["min"] = timezone.localdate().isoformat()

    class Meta:
        model = Intervention
        fields = ("action", "notes", "follow_up_date", "status")
        widgets = {"follow_up_date": forms.DateInput(attrs={"type": "date"})}

    def clean(self):
        data = super().clean()
        date, status = data.get("follow_up_date"), data.get("status")
        date_is_new = not self.instance.pk or "follow_up_date" in self.changed_data
        if status == "open" and date and date_is_new and date < timezone.localdate():
            self.add_error(
                "follow_up_date",
                "A follow-up date for an open action cannot be in the past. Choose today or a later date, "
                "or mark the action completed.",
            )
        return data
