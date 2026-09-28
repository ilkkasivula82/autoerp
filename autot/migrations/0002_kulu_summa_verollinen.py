"""Kulun verollinen summa: lisätään sarake ja täytetään olemassa oleville riveille."""

from decimal import ROUND_HALF_UP, Decimal

from django.db import migrations, models


def tayta_verolliset(apps, schema_editor):
    Kulu = apps.get_model("autot", "Kulu")
    for kulu in Kulu.objects.filter(summa_verollinen__isnull=True).iterator():
        arvo = Decimal(kulu.summa_veroton) * (100 + Decimal(kulu.alv_prosentti)) / 100
        kulu.summa_verollinen = int(arvo.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        kulu.save(update_fields=["summa_verollinen"])


class Migration(migrations.Migration):
    dependencies = [("autot", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="kulu",
            name="summa_verollinen",
            field=models.BigIntegerField(help_text="senttiä", null=True, verbose_name="summa (sis. alv)"),
        ),
        migrations.RunPython(tayta_verolliset, migrations.RunPython.noop),
    ]
