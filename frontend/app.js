const productsElement = document.getElementById("products");
const productSelect = document.getElementById("product");
const quantityInput = document.getElementById("quantity");
const emailInput = document.getElementById("email");
const form = document.getElementById("checkout-form");
const result = document.getElementById("result");
const submit = document.getElementById("submit");
let products = [];
let checkoutKey = null;

const money = cents => new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(cents / 100);

function updateTotal() {
  const product = products.find(item => item.id === productSelect.value);
  const quantity = Number(quantityInput.value) || 0;
  document.getElementById("total").textContent = money((product?.price_cents || 0) * quantity);
}

function showMessage(title, lines, isError = false, retry = null) {
  result.hidden = false;
  result.classList.toggle("error", isError);
  result.replaceChildren();
  const heading = document.createElement("h3");
  heading.textContent = title;
  result.append(heading);
  for (const line of lines) {
    const paragraph = document.createElement("p");
    paragraph.textContent = line;
    result.append(paragraph);
  }
  if (retry) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Retry processing";
    button.addEventListener("click", retry);
    result.append(button);
  }
}

function showOrder(order) {
  if (order.status === "CONFIRMED") {
    showMessage("Order confirmed", [
      `Order ${order.id}`,
      `${order.quantity} × ${order.product_name} · ${money(order.total_cents)}`,
      order.notification_status === "RECORDED" ? "Receipt notification recorded." : "Receipt record is pending. Use retry to check again."
    ], false, order.notification_status === "RECORDED" ? null : () => retryOrder(order.id));
  } else if (order.status === "REJECTED") {
    showMessage("Order could not be placed", [order.reason || "Stock was unavailable."], true);
  } else {
    showMessage("Order is pending", [order.reason || "Processing is still in progress.", `Order ${order.id}`], false, () => retryOrder(order.id));
  }
}

async function retryOrder(orderId) {
  try {
    const response = await fetch(`/api/orders/${encodeURIComponent(orderId)}/retry`, { method: "POST" });
    if (!response.ok) throw new Error("Could not retry this order.");
    const order = await response.json();
    showOrder(order.status === "PENDING" ? await waitForOrder(order.id) : order);
  } catch (error) {
    showMessage("Retry failed", [error.message], true);
  }
}

async function waitForOrder(orderId) {
  for (let attempt = 0; attempt < 20; attempt++) {
    await new Promise(resolve => setTimeout(resolve, 750));
    const response = await fetch(`/api/orders/${encodeURIComponent(orderId)}`);
    if (!response.ok) throw new Error("Could not check the order status.");
    const order = await response.json();
    if (order.status !== "PENDING") return order;
  }
  const response = await fetch(`/api/orders/${encodeURIComponent(orderId)}`);
  if (!response.ok) throw new Error("Could not check the order status.");
  return response.json();
}

function renderProducts() {
  productsElement.replaceChildren();
  productSelect.replaceChildren();
  for (const product of products) {
    const option = document.createElement("option");
    option.value = product.id;
    option.textContent = `${product.name} — ${money(product.price_cents)}`;
    productSelect.append(option);

    const card = document.createElement("article");
    card.className = "product-card";
    const image = document.createElement("div");
    image.className = "product-image";
    image.setAttribute("aria-hidden", "true");
    image.textContent = product.icon;
    const info = document.createElement("div");
    info.className = "product-info";
    const top = document.createElement("div");
    top.className = "product-top";
    const name = document.createElement("h3");
    name.textContent = product.name;
    const price = document.createElement("span");
    price.className = "price";
    price.textContent = money(product.price_cents);
    top.append(name, price);
    const description = document.createElement("p");
    description.textContent = product.description;
    const button = document.createElement("button");
    button.className = "pick-button";
    button.type = "button";
    button.textContent = "Choose this item ↗";
    button.addEventListener("click", () => {
      productSelect.value = product.id;
      checkoutKey = null;
      updateTotal();
      document.getElementById("checkout").scrollIntoView({ behavior: "smooth" });
    });
    info.append(top, description, button);
    card.append(image, info);
    productsElement.append(card);
  }
  updateTotal();
}

async function loadProducts() {
  try {
    const response = await fetch("/api/products");
    if (!response.ok) throw new Error("Catalog is unavailable.");
    products = await response.json();
    renderProducts();
  } catch (error) {
    productsElement.textContent = "Products could not be loaded. Please refresh and try again.";
    productSelect.replaceChildren();
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  submit.disabled = true;
  if (!checkoutKey) checkoutKey = crypto.randomUUID();
  try {
    const response = await fetch("/api/orders", {
      method: "POST",
      headers: { "Content-Type": "application/json", "Idempotency-Key": checkoutKey },
      body: JSON.stringify({ product_id: productSelect.value, quantity: Number(quantityInput.value), email: emailInput.value })
    });
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(typeof body.detail === "string" ? body.detail : "Could not place the order.");
    }
    const order = await response.json();
    if (order.status === "PENDING") {
      showMessage("Order received", [`Order ${order.id}`, "Inventory is checking stock. You can watch the worker process it in the logs."]);
      showOrder(await waitForOrder(order.id));
    } else {
      showOrder(order);
    }
    checkoutKey = null;
  } catch (error) {
    showMessage("Checkout failed", [error.message], true);
  } finally {
    submit.disabled = false;
  }
});

for (const field of [productSelect, quantityInput, emailInput]) {
  field.addEventListener("input", () => { checkoutKey = null; updateTotal(); });
}

loadProducts();
