package com.shema.app

import android.app.Activity
import android.content.Context
import android.os.Handler
import android.os.Looper
import android.util.Log
import com.android.billingclient.api.*

/**
 * Handles Google Play In-App Subscriptions (BillingClient v7).
 * Product ID: "shema_pro_yearly"
 * Price: ₪99.90 / year ($29.99 / year) with 14 days free trial.
 *
 * Implements offline tolerance & trial support so users can use Shema completely
 * locally without requiring constant internet access.
 */
class BillingManager(private val context: Context, private val listener: BillingCallback) {

    interface BillingCallback {
        fun onSubscriptionStatusChanged(isSubscribed: Boolean, isTrial: Boolean, daysRemaining: Int)
        fun onProductPriceLoaded(priceFormatted: String, billingPeriod: String)
        fun onBillingError(message: String)
    }

    companion object {
        const val TAG = "ShemaBilling"
        const val SUBSCRIPTION_ID = "shema_pro_yearly"
        const val TRIAL_DAYS = 14
        const val TRIAL_MS = TRIAL_DAYS * 24 * 60 * 60 * 1000L
    }

    private val mainHandler = Handler(Looper.getMainLooper())
    private var billingClient: BillingClient? = null
    private var productDetails: ProductDetails? = null
    private var isConnected = false

    private val purchasesUpdatedListener = PurchasesUpdatedListener { billingResult, purchases ->
        if (billingResult.responseCode == BillingClient.BillingResponseCode.OK && purchases != null) {
            for (purchase in purchases) {
                handlePurchase(purchase)
            }
        } else if (billingResult.responseCode == BillingClient.BillingResponseCode.USER_CANCELED) {
            Log.d(TAG, "User canceled billing flow")
        } else {
            Log.e(TAG, "Billing error: ${billingResult.debugMessage}")
            mainHandler.post { listener.onBillingError("שגיאת רכישה: ${billingResult.debugMessage}") }
        }
    }

    init {
        initBillingClient()
    }

    private fun initBillingClient() {
        billingClient = BillingClient.newBuilder(context)
            .setListener(purchasesUpdatedListener)
            .enablePendingPurchases(PendingPurchasesParams.newBuilder().enableOneTimeProducts().enablePrepaidPlans().build())
            .build()

        startConnection()
    }

    fun startConnection() {
        billingClient?.startConnection(object : BillingClientStateListener {
            override fun onBillingSetupFinished(billingResult: BillingResult) {
                if (billingResult.responseCode == BillingClient.BillingResponseCode.OK) {
                    isConnected = true
                    Log.d(TAG, "Billing connected successfully")
                    queryProductDetails()
                    checkActiveSubscriptions()
                } else {
                    isConnected = false
                    Log.w(TAG, "Billing setup failed: ${billingResult.debugMessage}")
                    // Still evaluate local trial/cached subscription state
                    evaluateEntitlement()
                }
            }

            override fun onBillingServiceDisconnected() {
                isConnected = false
                Log.w(TAG, "Billing service disconnected, will retry later")
            }
        })
    }

    private fun queryProductDetails() {
        val productList = listOf(
            QueryProductDetailsParams.Product.newBuilder()
                .setProductId(SUBSCRIPTION_ID)
                .setProductType(BillingClient.ProductType.SUBS)
                .build()
        )

        val params = QueryProductDetailsParams.newBuilder()
            .setProductList(productList)
            .build()

        billingClient?.queryProductDetailsAsync(params) { billingResult, queryResult ->
            val list = queryResult.productDetailsList
            if (billingResult.responseCode == BillingClient.BillingResponseCode.OK && !list.isNullOrEmpty()) {
                productDetails = list.first()
                val subOffer = productDetails?.subscriptionOfferDetails?.firstOrNull()
                val price = subOffer?.pricingPhases?.pricingPhaseList?.lastOrNull()?.formattedPrice ?: "₪99.90"
                mainHandler.post {
                    listener.onProductPriceLoaded(price, "שנה")
                }
            } else {
                Log.w(TAG, "Failed to load product details: ${billingResult.debugMessage}")
            }
        }
    }

    fun checkActiveSubscriptions() {
        if (!isConnected) {
            evaluateEntitlement()
            return
        }

        val params = QueryPurchasesParams.newBuilder()
            .setProductType(BillingClient.ProductType.SUBS)
            .build()

        billingClient?.queryPurchasesAsync(params) { billingResult, purchases ->
            if (billingResult.responseCode == BillingClient.BillingResponseCode.OK) {
                var hasActiveSub = false
                for (purchase in purchases) {
                    if (purchase.products.contains(SUBSCRIPTION_ID) &&
                        purchase.purchaseState == Purchase.PurchaseState.PURCHASED) {
                        hasActiveSub = true
                        if (!purchase.isAcknowledged) {
                            acknowledgePurchase(purchase)
                        }
                    }
                }
                Prefs.setSubscribed(context, hasActiveSub)
                evaluateEntitlement()
            } else {
                evaluateEntitlement()
            }
        }
    }

    private fun handlePurchase(purchase: Purchase) {
        if (purchase.purchaseState == Purchase.PurchaseState.PURCHASED) {
            if (!purchase.isAcknowledged) {
                acknowledgePurchase(purchase)
            } else {
                Prefs.setSubscribed(context, true)
                evaluateEntitlement()
            }
        }
    }

    private fun acknowledgePurchase(purchase: Purchase) {
        val params = AcknowledgePurchaseParams.newBuilder()
            .setPurchaseToken(purchase.purchaseToken)
            .build()

        billingClient?.acknowledgePurchase(params) { billingResult ->
            if (billingResult.responseCode == BillingClient.BillingResponseCode.OK) {
                Prefs.setSubscribed(context, true)
                evaluateEntitlement()
            }
        }
    }

    fun launchBillingFlow(activity: Activity): Boolean {
        val details = productDetails ?: run {
            mainHandler.post { listener.onBillingError("נתוני המנוי עדיין בטעינה, אנא נסה שוב בעוד רגע") }
            queryProductDetails()
            return false
        }

        val offerToken = details.subscriptionOfferDetails?.firstOrNull()?.offerToken ?: ""
        val productDetailsParams = BillingFlowParams.ProductDetailsParams.newBuilder()
            .setProductDetails(details)
            .setOfferToken(offerToken)
            .build()

        val billingFlowParams = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(listOf(productDetailsParams))
            .build()

        val result = billingClient?.launchBillingFlow(activity, billingFlowParams)
        return result?.responseCode == BillingClient.BillingResponseCode.OK
    }

    /**
     * Evaluates whether the user currently has access:
     * Either active Google Play subscription OR within the 14-day free trial.
     */
    fun evaluateEntitlement(): Boolean {
        val isSubscribed = Prefs.isSubscribed(context)
        val installTime = Prefs.firstInstallTime(context)
        val now = System.currentTimeMillis()
        val trialElapsed = now - installTime
        val trialActive = trialElapsed < TRIAL_MS
        val daysRemaining = if (trialActive) {
            (((TRIAL_MS - trialElapsed) / (1000 * 60 * 60 * 24)) + 1).toInt()
        } else 0

        val hasAccess = isSubscribed || trialActive

        mainHandler.post {
            listener.onSubscriptionStatusChanged(
                isSubscribed = isSubscribed,
                isTrial = !isSubscribed && trialActive,
                daysRemaining = daysRemaining
            )
        }
        return hasAccess
    }
}
