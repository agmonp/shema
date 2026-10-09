package app.shema.listener

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/** Phone restarted / app updated: listening was stopped. Android 14+ forbids starting a microphone
 *  service from here, so ask the user with one tap (the tap opens the app, which starts it). */
class BootReceiver : BroadcastReceiver() {
    override fun onReceive(c: Context, i: Intent) {
        if (!Prefs.wanted(c)) return
        val nm = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        nm.createNotificationChannel(NotificationChannel("restart", "הפעלה מחדש", NotificationManager.IMPORTANCE_HIGH))
        val open = PendingIntent.getActivity(c, 0, Intent(c, MainActivity::class.java).putExtra("autostart", true),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        nm.notify(2, Notification.Builder(c, "restart")
            .setSmallIcon(R.drawable.ic_stat)
            .setContentTitle("שמע כבוי")
            .setContentText("הטלפון הופעל מחדש. הקש כדי להתחיל להקשיב.")
            .setContentIntent(open).setAutoCancel(true).build())
    }
}
