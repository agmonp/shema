package app.shema.listener

import java.io.ByteArrayOutputStream
import java.io.File

/**
 * Minimal Ogg-Opus writer (RFC 7845). Android's own MediaMuxer(OGG) puts every 20 ms packet in a page of its own
 * (28 bytes of header per ~30 byte packet), which doubled the size of a 12 kbps file. Here ~1 s of packets share a page.
 */
class OggOpus(private val head: ByteArray, private val preSkip: Int) {
    private val packets = ArrayList<ByteArray>()
    private val samples = ArrayList<Int>()           // 48 kHz samples in each packet

    fun add(p: ByteArray) { packets.add(p); samples.add(packetSamples(p)) }
    fun count() = packets.size

    /** [pcmSamples16k] = real length of the input, so the last page's granule position trims the encoder's padding. */
    fun write(out: File, pcmSamples16k: Int) {
        val bos = ByteArrayOutputStream()
        val serial = 0x5A3C1E07
        var seq = 0
        fun page(flags: Int, granule: Long, pk: List<ByteArray>) {
            val lacing = ByteArrayOutputStream()
            for (p in pk) {
                var n = p.size
                while (n >= 255) { lacing.write(255); n -= 255 }
                lacing.write(n)
            }
            val lac = lacing.toByteArray()
            val body = ByteArrayOutputStream()
            for (p in pk) body.write(p)
            val b = body.toByteArray()
            val h = ByteArray(27 + lac.size + b.size)
            "OggS".toByteArray().copyInto(h, 0)
            h[4] = 0; h[5] = flags.toByte()
            for (i in 0 until 8) h[6 + i] = (granule shr (8 * i)).toByte()
            for (i in 0 until 4) { h[14 + i] = (serial shr (8 * i)).toByte(); h[18 + i] = (seq shr (8 * i)).toByte() }
            h[26] = lac.size.toByte()
            lac.copyInto(h, 27); b.copyInto(h, 27 + lac.size)
            val crc = crc(h)
            for (i in 0 until 4) h[22 + i] = (crc shr (8 * i)).toByte()
            bos.write(h); seq++
        }
        page(0x02, 0, listOf(head))
        val tags = ByteArrayOutputStream().apply {
            write("OpusTags".toByteArray()); val v = "shema".toByteArray()
            for (i in 0 until 4) write(v.size shr (8 * i)); write(v)
            for (i in 0 until 4) write(0)
        }.toByteArray()
        page(0, 0, listOf(tags))
        var i = 0
        var total = 0L
        val limit = pcmSamples16k.toLong() * 3 + preSkip
        while (i < packets.size) {
            val group = ArrayList<ByteArray>()
            var segs = 0
            while (i < packets.size && group.size < 50 && segs + packets[i].size / 255 + 1 <= 255) {
                group.add(packets[i]); segs += packets[i].size / 255 + 1; total += samples[i]; i++
            }
            if (group.isEmpty()) { group.add(packets[i]); total += samples[i]; i++ }
            val last = i >= packets.size
            page(if (last) 0x04 else 0, if (last) minOf(total + preSkip, maxOf(limit, preSkip.toLong() + 1)) else total + preSkip, group)
        }
        out.writeBytes(bos.toByteArray())
    }

    companion object {
        private val table = IntArray(256).also {
            for (n in 0 until 256) { var c = n shl 24; repeat(8) { c = if (c and 0x80000000.toInt() != 0) (c shl 1) xor 0x04C11DB7 else c shl 1 }; it[n] = c }
        }
        private fun crc(b: ByteArray): Int {
            var c = 0
            for (x in b) c = (c shl 8) xor table[((c ushr 24) xor (x.toInt() and 0xFF)) and 0xFF]
            return c
        }

        fun opusHead(preSkip: Int): ByteArray {
            val h = ByteArray(19)
            "OpusHead".toByteArray().copyInto(h, 0)
            h[8] = 1; h[9] = 1                                  // version, mono
            h[10] = preSkip.toByte(); h[11] = (preSkip shr 8).toByte()
            val r = 16000                                       // original input rate (informational)
            for (i in 0 until 4) h[12 + i] = (r shr (8 * i)).toByte()
            return h                                            // gain 0, mapping family 0
        }

        /** duration of one Opus packet in 48 kHz samples, from its TOC byte */
        fun packetSamples(p: ByteArray): Int {
            if (p.isEmpty()) return 960
            val toc = p[0].toInt() and 0xFF
            val cfg = toc shr 3
            val frame = when {
                cfg < 12 -> intArrayOf(480, 960, 1920, 2880)[cfg % 4]
                cfg < 16 -> if (cfg % 2 == 0) 480 else 960
                else -> intArrayOf(120, 240, 480, 960)[cfg % 4]
            }
            val frames = when (toc and 3) { 0 -> 1; 1, 2 -> 2; else -> if (p.size > 1) p[1].toInt() and 0x3F else 1 }
            return frame * frames
        }
    }
}
