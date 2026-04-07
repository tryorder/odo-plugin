/** @odoo-module **/

import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";

class PosSyncPage extends Component {
    setup() {
        this.notification = useService("notification");
        this.orm = this.env.services.orm;
        this.state = useState({ loading: false });
    }

    async syncProducts() {
        this.state.loading = true;

        try {
            // Call the model method `sync_products` directly
            const data = await this.orm.call(
                "pos.sync.service",  // model
                "sync_products",     // method
                [],                  // args
                { context: {} }      // optional context
            );

            if (data.success) {
                this.notification.add("Products synced successfully!", {
                    type: "success",
                });
                console.log("Sync response:", data);
            } else {
                this.notification.add("Error syncing products!", {
                    type: "danger",
                });
                console.error("Sync error:", data);
            }
        } catch (error) {
            console.error("Unexpected error:", error);
            this.notification.add(`Error syncing products: ${error.message}`, {
                type: "danger",
            });
        } finally {
            this.state.loading = false;
        }
    }
}

PosSyncPage.template = "pos_sync_page.Template";

// Register the client action
registry.category("actions").add("pos_sync_page", PosSyncPage);
