package com.shema.app

import android.content.Intent
import android.service.quicksettings.Tile
import android.service.quicksettings.TileService

/** Quick-settings tile: "mark this moment" (the PC keeps that conversation and its recording). */
class MarkTile : TileService() {
    override fun onStartListening() {
        qsTile?.apply {
            label = "סמן רגע"
            state = if (ListenService.on) Tile.STATE_INACTIVE else Tile.STATE_UNAVAILABLE
            updateTile()
        }
    }

    override fun onClick() {
        if (ListenService.on) {
            startService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_MARK))
            android.widget.Toast.makeText(this, "⭐ הרגע סומן", android.widget.Toast.LENGTH_SHORT).show()
        } else android.widget.Toast.makeText(this, "ההקשבה כבויה", android.widget.Toast.LENGTH_SHORT).show()
    }
}

/** Quick-settings tile: "pause" -- nothing is recorded until tapped again (the app's one pause). */
class PrivateTile : TileService() {
    override fun onStartListening() {
        qsTile?.apply {
            label = if (ListenService.pausedNow) "שמע מושהה" else "השהה את שמע"
            state = when { !ListenService.on -> Tile.STATE_UNAVAILABLE; ListenService.pausedNow -> Tile.STATE_ACTIVE; else -> Tile.STATE_INACTIVE }
            updateTile()
        }
    }

    override fun onClick() {
        if (!ListenService.on) return
        val nowPaused = !ListenService.pausedNow
        startService(Intent(this, ListenService::class.java).setAction(ListenService.ACTION_TOGGLE))
        qsTile?.apply {
            state = if (nowPaused) Tile.STATE_ACTIVE else Tile.STATE_INACTIVE
            label = if (nowPaused) "שמע מושהה" else "השהה את שמע"
            updateTile()
        }
    }
}
