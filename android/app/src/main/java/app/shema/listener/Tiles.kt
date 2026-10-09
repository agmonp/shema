package app.shema.listener

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

/** Quick-settings tile: "private now" = mute for an hour; tap again to listen again. */
class PrivateTile : TileService() {
    private fun muted() = ListenService.mutedUntilNow > System.currentTimeMillis()

    override fun onStartListening() {
        qsTile?.apply {
            label = "פרטי עכשיו"
            state = when { !ListenService.on -> Tile.STATE_UNAVAILABLE; muted() -> Tile.STATE_ACTIVE; else -> Tile.STATE_INACTIVE }
            updateTile()
        }
    }

    override fun onClick() {
        if (!ListenService.on) return
        startService(Intent(this, ListenService::class.java)
            .setAction(if (muted()) ListenService.ACTION_UNMUTE else ListenService.ACTION_MUTE_HOUR))
        qsTile?.apply { state = if (muted()) Tile.STATE_INACTIVE else Tile.STATE_ACTIVE; updateTile() }
    }
}
