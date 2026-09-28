from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("liikkeet", "0003_liike_yhteystiedot")]

    operations = [
        migrations.AddField(
            model_name="liike",
            name="marginaalimenettely",
            field=models.CharField(
                choices=[("kuukausi", "Kuukausikohtainen"), ("tavara", "Tavarakohtainen")],
                default="kuukausi",
                help_text="Kuukausikohtaisessa tappiollinen kauppa pienentää kuukauden veroa.",
                max_length=10,
                verbose_name="voittomarginaaliverotuksen menettely",
            ),
        ),
        migrations.AddField(
            model_name="liike",
            name="maksuaika_pv",
            field=models.PositiveSmallIntegerField(default=14, verbose_name="laskujen maksuaika (pv)"),
        ),
    ]
