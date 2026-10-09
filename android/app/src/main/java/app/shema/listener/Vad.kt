package app.shema.listener

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import java.nio.FloatBuffer

/**
 * Silero VAD v4 (k2-fsa export, 16 kHz only): x [1,512] float, h/c [2,1,64] -> prob [1,1].
 * The same model the PC uses (voice_models/silero_vad.onnx), so phone and PC agree on "speech".
 */
class Vad(context: Context) : AutoCloseable {
    companion object { const val FRAME = 512 }            // 32 ms at 16 kHz

    private val env = OrtEnvironment.getEnvironment()
    private val session: OrtSession
    private var h = FloatArray(2 * 64)
    private var c = FloatArray(2 * 64)

    init {
        val bytes = context.assets.open("silero_vad.onnx").use { it.readBytes() }
        session = env.createSession(bytes, OrtSession.SessionOptions().apply { setIntraOpNumThreads(1) })
    }

    fun reset() { h = FloatArray(2 * 64); c = FloatArray(2 * 64) }

    /** pcm: exactly FRAME samples -> speech probability 0..1 */
    fun prob(pcm: ShortArray): Float {
        val x = FloatArray(FRAME) { pcm[it] / 32768f }
        val shapeS = longArrayOf(2, 1, 64)
        OnnxTensor.createTensor(env, FloatBuffer.wrap(x), longArrayOf(1, FRAME.toLong())).use { tx ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(h), shapeS).use { th ->
                OnnxTensor.createTensor(env, FloatBuffer.wrap(c), shapeS).use { tc ->
                    session.run(mapOf("x" to tx, "h" to th, "c" to tc)).use { r ->
                        @Suppress("UNCHECKED_CAST")
                        val p = (r[0].value as Array<FloatArray>)[0][0]
                        h = flatten(r[1].value); c = flatten(r[2].value)
                        return p
                    }
                }
            }
        }
    }

    @Suppress("UNCHECKED_CAST")
    private fun flatten(v: Any): FloatArray {
        val a = v as Array<Array<FloatArray>>
        val out = FloatArray(2 * 64)
        var i = 0
        for (x in a) for (y in x) for (z in y) out[i++] = z
        return out
    }

    override fun close() { session.close() }
}
