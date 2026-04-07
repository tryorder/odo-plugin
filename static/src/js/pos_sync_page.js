/** @odoo-module **/


import { registry } from "@web/core/registry";
import { Component, useState } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";

class PosSyncPage extends Component {
    
    setup() {
        this.notification = useService("notification");
        this.state = useState({ loading: false });
        this.rpc = rpc;
    }


    async syncProducts () {

        this.state.loading = true;

        try {

           //const products = await  this.rpc(url, params, { silent: true });

            // const productJson = await this.rpc({
            //     model: "product.product",
            //     method: "search_read",
            //     args: [[], []],
            // });



            // 1. Get products from Odoo

            const products = await this.env.services.orm.call(
                "product.template",
                "search_read",
              //  [[], ["id", "name", "list_price", "default_code", "barcode"]]
            );


            console.log("productJson", products);



            // 2. Send products to external API

            const response = await fetch("/pos/sync", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                     "X-Requested-With": "XMLHttpRequest"  // important for Odoo
                },
                body: JSON.stringify({})

            });

            const data = await response.json();
            if (data.success) {
                console.log("Products synced:", data.data);
            } else {
                console.error("Error syncing products booom");
                console.log("Products:", data.data);

            }

            // 3. Show success notification

            this.notification.add(
                `Successfully synced`,
                { type: "success" }
            );

            console.log("External API Response:", data);



        } catch (error) {
            console.error(error);
              this.notification.add(
                    `Error syncing products boom: ${error.message}`,
                    { type: "danger" }
                );

        } finally {
            this.state.loading = false;
        }
    };

}

// The template name must match t-name in XML exactly
PosSyncPage.template = "pos_sync_page.Template";

// Register the client action
registry.category("actions").add("pos_sync_page", PosSyncPage);
