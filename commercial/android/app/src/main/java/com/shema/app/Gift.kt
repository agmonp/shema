package com.shema.app

import android.content.Context
import android.provider.Settings
import android.util.Base64
import java.security.KeyFactory
import java.security.MessageDigest
import java.security.Signature
import java.security.spec.X509EncodedKeySpec

/**
 * Free "שמע Pro" for people the owner chooses, one phone each.
 * The phone shows its phone code (from ANDROID_ID, which stays the same across reinstalls of this app);
 * the owner signs it on the PC (commercial/scripts/gift.ps1, private key never in the repository) and sends back
 * SHEMA-<payload+signature>. Only the public key is here, so nobody can make codes from this source.
 * Payload: version 1 | phone (5 bytes) | last day (days since 1970, 2 bytes, 0 = forever) | name (UTF-8).
 */
object Gift {
    private const val PUBLIC_KEY =
        "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE32FXhghUNac1NeHZHShGLidjSyXfiDvjjaeVCRZ6db3C/HtuVHmjNuAYykp28TBpDz35fJz6dZdYhOnbsduKIw=="
    private const val ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   // Crockford base32: no I, L, O, U
    private val CODE = Regex("SHEMA-[0-9A-Za-z]{100,}")
    /** phones whose gift was taken back (written by the gift dashboard, commercial/dashboard; takes effect in the next app version) */
    private val REVOKED = setOf<String>()  // dashboard:revoked

    class Info(val name: String, val until: Long)                     // until: ms, 0 = forever
    sealed class Result {
        class Ok(val info: Info) : Result()
        object OtherPhone : Result()
        object Expired : Result()
        object Revoked : Result()
        object Invalid : Result()
    }

    private fun phoneBytes(c: Context): ByteArray {
        val id = Settings.Secure.getString(c.contentResolver, Settings.Secure.ANDROID_ID)
            ?: Prefs.fallbackId(c)
        return MessageDigest.getInstance("SHA-256").digest("shema-phone|$id".toByteArray()).copyOf(5)
    }

    /** e.g. K7Q2-M9XD: what the friend sends the owner */
    fun phoneCode(c: Context) = b32(phoneBytes(c)).chunked(4).joinToString("-")

    /** the SHEMA-... code inside a pasted message, if any */
    fun find(text: CharSequence?) = text?.let { CODE.find(it)?.value }

    fun check(c: Context, text: String): Result {
        val raw = b32decode(find(text)?.removePrefix("SHEMA-") ?: return Result.Invalid) ?: return Result.Invalid
        if (raw.size < 8 + 64 || raw[0] != 1.toByte()) return Result.Invalid
        val payload = raw.copyOfRange(0, raw.size - 64)
        val ok = try {
            val key = KeyFactory.getInstance("EC").generatePublic(X509EncodedKeySpec(Base64.decode(PUBLIC_KEY, Base64.DEFAULT)))
            Signature.getInstance("SHA256withECDSA").run {
                initVerify(key); update("shema-gift-v1".toByteArray()); update(payload)
                verify(der(raw.copyOfRange(raw.size - 64, raw.size)))
            }
        } catch (e: Exception) { false }
        if (!ok) return Result.Invalid
        if (!payload.copyOfRange(1, 6).contentEquals(phoneBytes(c))) return Result.OtherPhone
        if (phoneCode(c) in REVOKED) return Result.Revoked
        val days = ((payload[6].toInt() and 0xFF) shl 8) or (payload[7].toInt() and 0xFF)
        val until = if (days == 0) 0L else (days + 1) * 86_400_000L
        if (until != 0L && until < System.currentTimeMillis()) return Result.Expired
        return Result.Ok(Info(String(payload, 8, payload.size - 8, Charsets.UTF_8), until))
    }

    /** the stored gift, checked again every time (a copied settings file is worth nothing on another phone) */
    fun info(c: Context): Info? = Prefs.gift(c).takeIf { it.isNotEmpty() }?.let { (check(c, it) as? Result.Ok)?.info }
    fun active(c: Context) = info(c) != null

    private fun b32(b: ByteArray): String {
        val sb = StringBuilder(); var acc = 0; var bits = 0
        for (x in b) {
            acc = ((acc shl 8) or (x.toInt() and 0xFF)) and 0xFFFF; bits += 8
            while (bits >= 5) { bits -= 5; sb.append(ALPHABET[(acc shr bits) and 31]) }
        }
        if (bits > 0) sb.append(ALPHABET[(acc shl (5 - bits)) and 31])
        return sb.toString()
    }

    private fun b32decode(s: String): ByteArray? {
        val out = java.io.ByteArrayOutputStream(); var acc = 0; var bits = 0
        for (ch in s.uppercase().replace('O', '0').replace('I', '1').replace('L', '1')) {
            val v = ALPHABET.indexOf(ch); if (v < 0) return null
            acc = ((acc shl 5) or v) and 0xFFFF; bits += 5
            if (bits >= 8) { bits -= 8; out.write((acc shr bits) and 0xFF) }
        }
        return out.toByteArray()
    }

    /** r||s (what .NET signs) -> the DER form Java verifies */
    private fun der(rs: ByteArray): ByteArray {
        fun int(b: ByteArray): ByteArray {
            var i = 0
            while (i < b.size - 1 && b[i] == 0.toByte()) i++
            var v = b.copyOfRange(i, b.size)
            if (v[0] < 0) v = byteArrayOf(0) + v
            return byteArrayOf(0x02, v.size.toByte()) + v
        }
        val body = int(rs.copyOfRange(0, 32)) + int(rs.copyOfRange(32, 64))
        return byteArrayOf(0x30, body.size.toByte()) + body
    }
}
