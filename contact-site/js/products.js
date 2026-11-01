// Shop product data. Also the source of truth for the policies written in step 4.3.
// Warranty: laptops and phones 12 months, accessories 6 months.
const PRODUCTS = [
  { id: "LT-101", name: "AeroBook 14", category: "laptops", price: 42999,
    specs: "14-inch FHD, 8 GB RAM, 512 GB SSD, 1.3 kg", icon: "bi-laptop", featured: true },
  { id: "LT-102", name: "AeroBook Pro 16", category: "laptops", price: 79999,
    specs: "16-inch 2.5K, 16 GB RAM, 1 TB SSD, 12-hour battery", icon: "bi-laptop", featured: false },
  { id: "LT-103", name: "CampusLite 15", category: "laptops", price: 31999,
    specs: "15.6-inch FHD, 8 GB RAM, 256 GB SSD", icon: "bi-laptop", featured: false },
  { id: "PH-201", name: "Zenith X1", category: "phones", price: 24999,
    specs: "6.5-inch AMOLED, 128 GB, 5000 mAh battery", icon: "bi-phone", featured: true },
  { id: "PH-202", name: "Zenith X1 Pro", category: "phones", price: 34999,
    specs: "6.7-inch AMOLED 120 Hz, 256 GB, 50 MP camera", icon: "bi-phone", featured: false },
  { id: "PH-203", name: "Pulse Go", category: "phones", price: 11999,
    specs: "6.6-inch LCD, 64 GB, 5000 mAh battery", icon: "bi-phone", featured: false },
  { id: "AC-301", name: "SoundBud Air", category: "accessories", price: 2499,
    specs: "Wireless earbuds, 24-hour battery, Bluetooth 5.3", icon: "bi-earbuds", featured: true },
  { id: "AC-302", name: "PowerBrick 20000", category: "accessories", price: 1799,
    specs: "20000 mAh power bank, 22.5 W fast charge", icon: "bi-battery-charging", featured: false },
  { id: "AC-303", name: "TypeC Hub 7-in-1", category: "accessories", price: 1999,
    specs: "HDMI, USB 3.0, SD card, 100 W pass-through charging", icon: "bi-usb-c", featured: false }
];

function formatPrice(n) {
  return "\u20B9" + n.toLocaleString("en-IN");
}

// innerHTML is safe here: the data above is our own fixed list, not user input.
function productCard(p) {
  const col = document.createElement("div");
  col.className = "col-sm-6 col-lg-4";
  col.innerHTML =
    '<div class="card product-card h-100">' +
    '<div class="product-art"><i class="bi ' + p.icon + '"></i></div>' +
    '<div class="card-body d-flex flex-column">' +
    '<span class="badge text-bg-light border mb-2 align-self-start text-capitalize">' + p.category + "</span>" +
    '<h3 class="h5 card-title">' + p.name + "</h3>" +
    '<p class="card-text text-secondary small flex-grow-1">' + p.specs + "</p>" +
    '<div class="d-flex justify-content-between align-items-center">' +
    '<span class="fw-bold fs-5">' + formatPrice(p.price) + "</span>" +
    '<a href="contact.html" class="btn btn-sm btn-outline-brand">Ask about this</a>' +
    "</div></div></div>";
  return col;
}

function renderProducts(container, list) {
  container.innerHTML = "";
  list.forEach(function (p) { container.appendChild(productCard(p)); });
}

document.addEventListener("DOMContentLoaded", function () {
  const featured = document.getElementById("featured-products");
  if (featured) {
    renderProducts(featured, PRODUCTS.filter(function (p) { return p.featured; }));
  }
  const grid = document.getElementById("product-grid");
  if (grid) {
    renderProducts(grid, PRODUCTS);
    document.querySelectorAll("[data-filter]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        document.querySelectorAll("[data-filter]").forEach(function (b) { b.classList.remove("active"); });
        btn.classList.add("active");
        const f = btn.getAttribute("data-filter");
        renderProducts(grid, f === "all" ? PRODUCTS : PRODUCTS.filter(function (p) { return p.category === f; }));
      });
    });
  }
});
