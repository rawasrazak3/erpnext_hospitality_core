/**
 * Hospitality Analytics — v14 (Clean rewrite with null-safe chart rendering)
 * 
 * Key fixes from v13:
 * - Guards against undefined/NaN values in chart datasets (prevents SVG path errors)
 * - Uses Clone & Replace strategy for clean redraws (prevents removeChild errors)
 * - Charts only render after date filter selection
 */

frappe.provide('frappe.hospitality');

frappe.hospitality.FinalAnalyticsV14 = class {
    constructor() {
        this.fromDate = null;
        this.toDate = null;
        this.charts = [
            { id: 'chart-occ', name: 'Occupancy Rate Trend', type: 'line' },
            { id: 'chart-adr', name: 'Average Daily Rate (ADR)', type: 'line' },
            { id: 'chart-revpar', name: 'RevPAR Trend', type: 'line' },
            { id: 'chart-guest', name: 'Guest Type Distribution', type: 'pie' },
            { id: 'chart-revext', name: 'Revenue vs Expense Trend', type: 'line' },
            { id: 'chart-gp', name: 'Gross Profit Margin Trend', type: 'line' },
            { id: 'chart-exp', name: 'Expense Breakdown', type: 'donut' },
            { id: 'chart-reception', name: 'Sales by Reception', type: 'bar' },
            { id: 'chart-payment', name: 'Payment Mode Distribution', type: 'donut' },
            { id: 'chart-maintenance', name: 'Maintenance Cost by Room Type', type: 'bar' }
        ];
        this.setup_observer();
        this.init();
    }

    init() {
        if (!this.is_analytics_page()) return;
        this.inject_ui();
    }

    is_analytics_page() {
        const url = window.location.href;
        const page_name = frappe.container?.page?.page?.name || "";
        return url.includes('hospitality-analytics') || url.includes('hospitality_analytics') || page_name.includes('hospitality_analytics');
    }

    setup_observer() {
        const observer = new MutationObserver(() => {
            if (this.is_analytics_page() && !$('#hos-v14-controls-inner').length) {
                this.inject_ui();
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });
    }

    inject_ui() {
        const $target = $('#hos-v10-controls, [id*="AN_FINAL"]');
        if (!$target.length) return;

        $target.empty().append('<div id="hos-v14-controls-inner"></div>');
        const $inner = $('#hos-v14-controls-inner');

        $inner.html(`
            <div style="background: #111827; padding: 25px; border-radius: 12px; margin-bottom: 25px; border: 1px solid #374151;">
                <div class="row">
                    <div class="col-sm-4">
                        <label style="color: #9ca3af; font-size: 11px; font-weight: 800; text-transform: uppercase;">From Date</label>
                        <input type="date" id="v14-from-date" class="form-control" value="${this.fromDate || ''}" style="border-radius: 8px; font-weight: 700; border: 2px solid #374151; background: #1f2937; color: white;">
                    </div>
                    <div class="col-sm-4">
                        <label style="color: #9ca3af; font-size: 11px; font-weight: 800; text-transform: uppercase;">To Date</label>
                        <input type="date" id="v14-to-date" class="form-control" value="${this.toDate || ''}" style="border-radius: 8px; font-weight: 700; border: 2px solid #374151; background: #1f2937; color: white;">
                    </div>
                    <div class="col-sm-4" style="display: flex; align-items: flex-end;">
                        <button id="v14-draw-btn" class="btn btn-primary btn-block" style="font-weight: 800; height: 40px; border-radius: 8px; background: #3b82f6; border: none;">DRAW CHARTS</button>
                    </div>
                </div>
                <div id="v14-guide" style="margin-top: 15px; color: #6b7280; font-size: 12px; text-align: center;">
                    <i class="fa fa-info-circle"></i> Charts will only be drawn after you select a date range and click Draw.
                </div>
            </div>
        `);

        $('#v14-from-date, #v14-to-date').on('change', () => {
            this.fromDate = $('#v14-from-date').val();
            this.toDate = $('#v14-to-date').val();
            if (this.fromDate && this.toDate) {
                this.fetch_and_draw();
            }
        });

        $('#v14-draw-btn').on('click', () => {
            this.fromDate = $('#v14-from-date').val();
            this.toDate = $('#v14-to-date').val();
            if (!this.fromDate || !this.toDate) {
                frappe.msgprint(__('Please select both From and To dates first.'));
                return;
            }
            this.fetch_and_draw();
        });
    }

    /**
     * Sanitizes chart data to prevent SVG path errors.
     * Replaces undefined, NaN, null values with 0.
     * Ensures labels and values arrays are the same length.
     */
    sanitize_chart_data(data) {
        if (!data) return null;

        // Ensure labels exist and are valid
        if (!data.labels || !Array.isArray(data.labels)) return null;
        data.labels = data.labels.filter(l => l !== undefined && l !== null);
        
        if (data.labels.length === 0) return null;

        // Sanitize datasets
        if (data.datasets && Array.isArray(data.datasets)) {
            data.datasets = data.datasets.map(dataset => {
                if (dataset.values && Array.isArray(dataset.values)) {
                    // Replace undefined/NaN/null with 0
                    dataset.values = dataset.values.map(v => {
                        if (v === undefined || v === null || isNaN(v)) return 0;
                        return Number(v);
                    });

                    // Ensure values array matches labels length
                    while (dataset.values.length < data.labels.length) {
                        dataset.values.push(0);
                    }
                    dataset.values = dataset.values.slice(0, data.labels.length);
                }
                return dataset;
            });

            // Remove datasets that are entirely zeros
            // (keep at least one dataset)
            const nonEmptyDatasets = data.datasets.filter(ds => 
                ds.values && ds.values.some(v => v !== 0)
            );
            if (nonEmptyDatasets.length > 0) {
                data.datasets = nonEmptyDatasets;
            }
        }

        return data;
    }

    fetch_and_draw() {
        $('#v14-guide').html(`<span style="color: #3b82f6; font-weight: 700;">Fetching data...</span>`);

        this.charts.forEach(chart => {
            let el = document.getElementById(chart.id);
            if (!el || !el.parentNode) return;

            // Clone & Replace Strategy: Sever all ties to legacy chart observers
            const newEl = el.cloneNode(false);
            el.parentNode.replaceChild(newEl, el);
            el = newEl;

            el.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #9ca3af; font-style: italic;">Loading...</div>';

            frappe.call({
                method: 'hospitality_core.hospitality_core.dashboard_data.get_hospitality_analytics_data',
                args: {
                    chart_name: chart.name,
                    from_date: this.fromDate,
                    to_date: this.toDate
                },
                callback: (r) => {
                    const raw_data = r.message;
                    el.innerHTML = '';

                    // Sanitize data before rendering
                    const data = this.sanitize_chart_data(raw_data);

                    if (!data || !data.labels || data.labels.length === 0) {
                        el.innerHTML = '<div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #9ca3af;">No Data Found</div>';
                        return;
                    }

                    try {
                        const isCircle = chart.type === 'pie' || chart.type === 'donut';
                        const chartConfig = {
                            title: chart.name,
                            data: data,
                            type: chart.type,
                            height: 250,
                            colors: ['#6366f1', '#a855f7', '#f59e0b', '#10b981', '#ef4444', '#ec4899', '#06b6d4']
                        };

                        if (!isCircle) {
                            chartConfig.axisOptions = { xIsSeries: true, shortenYAxisNumbers: 1 };
                        }

                        new frappe.Chart(el, chartConfig);
                    } catch (err) {
                        el.innerHTML = `<div style="display: flex; align-items: center; justify-content: center; height: 100%; color: #ef4444; font-size: 12px;">Chart render error</div>`;
                        console.error(`Chart render error on ${chart.name}:`, err);
                    }
                }
            });
        });

        setTimeout(() => {
            $('#v14-guide').html(`<span style="color: #10b981; font-weight: 700;">Synced for ${this.fromDate} to ${this.toDate}</span>`);
        }, 1200);
    }
};

// Global Boot
$(document).on('page-change', () => {
    setTimeout(() => {
        window.hospitality_v14_manager = new frappe.hospitality.FinalAnalyticsV14();
    }, 1000);
});

if (document.readyState === 'complete') {
    window.hospitality_v14_manager = new frappe.hospitality.FinalAnalyticsV14();
}
