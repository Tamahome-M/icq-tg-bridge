// Contract of taxi.yandex.ru's own client, observed on 11 October 2026.
// Fail closed if its store/actions change. Never synthesize order HTTP requests.
(() => {
    const store = () => window.__tmmTaxiStore;
    const terminal = new Set(['complete', 'failed', 'cancelled', 'expired', 'preexpired']);
    const checkAuth = () => {
        const s = store().getState();
        if (s.session?.authStatus !== 'authorized' || !s.session?.userId) {
            throw new Error('TMM_TAXI_LOGIN');
        }
        return s;
    };
    const requireNative = () => {
        if (!window.__tmmTaxiRequire) {
            const chunks = window.webpackChunk_yandex_int_turboapp_taxi;
            if (!chunks?.push) throw new Error('TMM_TAXI_INTERFACE');
            chunks.push([['tmm-taxi-' + Date.now()], {}, r => { window.__tmmTaxiRequire = r; }]);
        }
        return window.__tmmTaxiRequire;
    };
    const findAction = prefix => {
        const r = requireNative();
        for (const [id, factory] of Object.entries(r.m)) {
            if (!factory.toString().includes('"' + prefix + '"')) continue;
            let exports;
            try { exports = r(id); } catch (_) { continue; }
            for (const fn of Object.values(exports)) {
                if (typeof fn === 'function' && fn.typePrefix === prefix) return fn;
            }
        }
        throw new Error('TMM_TAXI_INTERFACE');
    };
    const activeIds = s => {
        const p = s.orderSearch?.persist;
        if (!p || !s.orderSearch?.nonpersist?.isPersistedOrderInited) {
            throw new Error('TMM_TAXI_LOADING');
        }
        const ids = Object.entries(p.orders || {}).filter(([_, o]) =>
            o.info?.status && !terminal.has(o.info.status)).map(([id]) => id);
        if (p.activeOrderId && !ids.includes(p.activeOrderId) &&
            !terminal.has(p.orders?.[p.activeOrderId]?.info?.status)) ids.push(p.activeOrderId);
        for (const id of s.session.startupOrderIds || []) {
            if (typeof id !== 'string') throw new Error('TMM_TAXI_INTERFACE');
            if (!ids.includes(id) && !terminal.has(p.orders?.[id]?.info?.status)) ids.push(id);
        }
        return ids;
    };
    const paymentText = p => ({cash: 'Наличные', card: 'Карта, выбранная на сайте',
        corp: 'Корпоративная оплата', applepay: 'Apple Pay', googlepay: 'Google Pay'}[p.type] || p.type);
    const quote = () => {
        const s = checkAuth();
        const route = s.orderForm?.route;
        const road = s.tollRoads?.roadType;
        const estimate = s.orderEstimate?.roads?.[road];
        const selected = s.orderEstimate?.shared?.selectedEstimate;
        const payment = s.paymentMethods?.selectedPaymentMethod;
        if (!Array.isArray(route) || route.length !== 2 || route.some(p =>
            !p?.fullName || !Number.isFinite(p.point?.lon) || !Number.isFinite(p.point?.lat))) {
            throw new Error('TMM_TAXI_ROUTE');
        }
        if (!payment?.type || estimate?.ui?.isLoading || !estimate?.ui?.wasLoaded) {
            throw new Error('TMM_TAXI_ESTIMATE');
        }
        const currency = estimate.currencyRules?.code;
        if (!currency) throw new Error('TMM_TAXI_ESTIMATE');
        const levels = (estimate.serviceLevels || []).filter(f => !f.is_hidden && !f.full_auction &&
            f.name && Number.isFinite(f.price_raw) && f.price_raw >= 0);
        const fare = levels.find(f => f.class === selected);
        if (!fare) throw new Error('TMM_TAXI_ESTIMATE');
        const data = {account: s.session.userId, phoneId: s.session.personalPhoneId,
            route, selected, payment, road, currency, price: fare.price_raw,
            priceText: fare.price, description: fare.description,
            comment: s.orderForm.comment, requirements: s.requirements,
            params: s.orderParams, preorder: s.preorder, auction: s.orderForm.auction};
        const stable = JSON.stringify(data);
        const guard = JSON.stringify([data, estimate.estimates?.offer]);
        const placeText = p => p.fullName + (p.porchnumber ? ', подъезд ' + p.porchnumber : '');
        const priceText = f => (String(f.description || f.price || '').trim().startsWith('от ')
            ? 'от ' : '') + f.price_raw + ' ' + currency;
        return {origin: placeText(route[0]), destination: placeText(route[1]),
            route: route.map(p => [p.point.lon, p.point.lat]), road,
            fares: levels.map(f => ({code: f.class, title: f.name, price: priceText(f)})),
            selected, payment: paymentText(payment), paymentKey: {type: payment.type, id: payment.id},
            offer: estimate.estimates?.offer, price: fare.price_raw, currency, stable, guard};
    };
    window.__tmmTaxi = {
        snapshot: () => {
            const s = store().getState();
            return {authorized: s.session?.authStatus === 'authorized',
                loading: !s.session?.ui || s.session.ui.isLoading ||
                    !s.orderSearch?.nonpersist?.isPersistedOrderInited,
                account: s.session?.authStatus === 'authorized' ? s.session.userId : '',
                ids: s.session?.authStatus === 'authorized' ? activeIds(s) : [],
                paidOptions: !!s.orderForm?.PaidOptionsModalVisible};
        },
        quote,
        action: async ({prefix, payload, guard, extra, account, orderId}) => {
            // Only these observed native handlers may be invoked by the bridge.
            if (!new Set(['order-estimate/loadEstimate',
                'order-form/orderConfirm', 'order-form/orderConfirmStep2',
                'order/cancelOrder']).has(prefix)) throw new Error('TMM_TAXI_INTERFACE');
            const s = checkAuth();
            if (account && s.session.userId !== account) throw new Error('TMM_TAXI_LOGIN');
            const fn = findAction(prefix); // resolve before any mutation
            if (prefix.startsWith('order-form/orderConfirm')) {
                if (activeIds(s).length) throw new Error('TMM_TAXI_ACTIVE');
                if (!guard || quote().guard !== guard ||
                    !!s.orderForm.PaidOptionsModalVisible !== !!extra) throw new Error('TMM_TAXI_CHANGED');
            }
            if (prefix === 'order/cancelOrder') {
                const p = s.orderSearch.persist;
                if (p.activeOrderId !== orderId || p.orders?.[orderId]?.info?.cancel_state?.state !== 'free') {
                    throw new Error('TMM_TAXI_CHANGED');
                }
            }
            const result = await store().dispatch(fn(payload));
            if (result?.meta?.requestStatus === 'rejected') throw new Error('TMM_TAXI_API');
        },
        resetRoute: () => {
            const s = checkAuth();
            if (activeIds(s).length) throw new Error('TMM_TAXI_ACTIVE');
            store().dispatch({type: 'order-form/hidePaidOptionsModal'});
            store().dispatch({type: 'order-form/resetRoute'});
        },
        dismissConfirmation: () => {
            checkAuth();
            store().dispatch({type: 'order-form/hidePaidOptionsModal'});
        },
        // Use the client's CSRF/auth middleware; breakReason is deliberately absent.
        trip: async ({id, account}) => {
            const s = checkAuth();
            if (s.session.userId !== account) throw new Error('TMM_TAXI_LOGIN');
            const r = requireNative();
            for (const [key, factory] of Object.entries(r.m)) {
                if (!factory.toString().includes('"/3.0/taxiontheway"')) continue;
                let exports;
                try { exports = r(key); } catch (_) { continue; }
                for (const fn of Object.values(exports)) {
                    if (typeof fn !== 'function' || !fn.toString().includes('"/3.0/taxiontheway"')) continue;
                    const response = await fn({orderId: id, userId: s.session.userId,
                        personalPhoneId: s.session.personalPhoneId});
                    if (!response?.data?.status) throw new Error('TMM_TAXI_API');
                    return response.data;
                }
            }
            throw new Error('TMM_TAXI_INTERFACE');
        },
    };
})();
