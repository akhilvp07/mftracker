# Generated migration for adding HOLDING transaction type and is_open field

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('portfolio', '0005_casimport_purchaselot_cas_transaction_id_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='purchaselot',
            name='transaction_type',
            field=models.CharField(
                choices=[
                    ('PURCHASE', 'Purchase'),
                    ('REDEMPTION', 'Redemption'),
                    ('SWITCH_IN', 'Switch In'),
                    ('SWITCH_OUT', 'Switch Out'),
                    ('DIVIDEND_REINVEST', 'Dividend Reinvest'),
                    ('HOLDING', 'Current Holding')
                ],
                default='PURCHASE',
                max_length=20
            ),
        ),
        migrations.AddField(
            model_name='purchaselot',
            name='is_open',
            field=models.BooleanField(default=True),
        ),
    ]
