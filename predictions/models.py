from django.db import models

class DelayPrediction(models.Model):
    route = models.ForeignKey('routes.Route', on_delete=models.CASCADE)
    stop = models.ForeignKey('stops.Stop', on_delete=models.CASCADE)
    predicted_delay_minutes = models.FloatField()
    weather_condition = models.CharField(max_length=100)
    temperature = models.FloatField()
    traffic_level = models.CharField(max_length=50)
    hour_of_day = models.IntegerField()
    day_of_week = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.route} at {self.stop} — {self.predicted_delay_minutes} min delay"