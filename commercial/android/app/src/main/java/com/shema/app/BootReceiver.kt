package com.shema.app

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
        Reminders.rearm(c)                                   // alarms do not survive a restart / update
        if (!Prefs.wanted(c)) return
        askToStart(c)
    }

    companion object {
        /** one tap opens the app, which starts listening (an activity may start a microphone service).
         *  The launcher intent, not MainActivity::class: Play's Android 15 check follows a class reference from boot
         *  code into MainActivity -> startForegroundService(ListenService) and flags it (1.0.17 / 1.0.18). */
        fun askToStart(c: Context, why: String = "הטלפון הופעל מחדש") {
            val nm = c.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
            nm.createNotificationChannel(NotificationChannel("restart", "הפעלה מחדש", NotificationManager.IMPORTANCE_HIGH))
            val launch = c.packageManager.getLaunchIntentForPackage(c.packageName) ?: return
            val open = PendingIntent.getActivity(c, 0, launch, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
            nm.notify(2, Notification.Builder(c, "restart")
                .setSmallIcon(R.drawable.ic_stat)
                .setContentTitle("שמע Pro כבוי")
                .setContentText("$why. הקש כדי להתחיל להקשיב.")
                .setContentIntent(open).setAutoCancel(true).build())
        }
    }
}
