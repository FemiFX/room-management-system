(function () {
    const userMenuBtn = document.getElementById("userMenuButton");
    const userMenu = document.getElementById("userMenu");
    const userDropdownIcon = document.getElementById("user-dropdown-icon");
    const themeToggle = document.getElementById("themeToggle");
    const themeIcon = document.getElementById("themeIcon");
    const htmlEl = document.documentElement;

    // User menu
    userMenuBtn?.addEventListener("click", (e) => {
        e.stopPropagation();
        const isOpen = userMenu?.classList.contains("open");
        userMenu?.classList.toggle("open", !isOpen);
        userMenuBtn.setAttribute("aria-expanded", (!isOpen).toString());
        userDropdownIcon?.classList.toggle("rotate-180", !isOpen);
    });
    document.addEventListener("click", (e) => {
        if (
            userMenu &&
            userMenuBtn &&
            !userMenu.contains(e.target) &&
            !userMenuBtn.contains(e.target)
        ) {
            userMenu.classList.remove("open");
            userMenuBtn.setAttribute("aria-expanded", "false");
            userDropdownIcon?.classList.remove("rotate-180");
        }
    });

    // Theme toggle
    const storedTheme = localStorage.getItem("theme") || "light";
    if (storedTheme === "dark") {
        htmlEl.classList.add("dark");
        htmlEl.style.colorScheme = "dark";
        themeIcon?.classList.remove("fa-moon");
        themeIcon?.classList.add("fa-sun");
    } else {
        htmlEl.style.colorScheme = "light";
    }

    themeToggle?.addEventListener("click", () => {
        htmlEl.classList.toggle("dark");
        const isDark = htmlEl.classList.contains("dark");
        themeIcon?.classList.toggle("fa-moon", !isDark);
        themeIcon?.classList.toggle("fa-sun", isDark);
        htmlEl.style.colorScheme = isDark ? "dark" : "light";
        localStorage.setItem("theme", isDark ? "dark" : "light");
    });

    // Notifications
    const notificationButton = document.getElementById("notification-button");
    const notificationDropdown = document.getElementById("notification-dropdown");
    const notificationBadge = document.getElementById("notification-badge");
    const markAllBtn = document.getElementById("mark-all-read");
    const csrfToken = document
        .querySelector('meta[name="csrf-token"]')
        ?.getAttribute("content");
    const unreadBorderClasses = [
        "border-l-turf-green",
        "dark:border-l-golden-bronze",
        "bg-turf-green/[0.04]",
        "dark:bg-golden-bronze/[0.04]",
    ];
    const readBorderClasses = ["border-l-transparent"];

    function toggleDropdown(forceOpen = null) {
        if (!notificationDropdown) return;
        const shouldOpen =
            forceOpen !== null
                ? forceOpen
                : notificationDropdown.classList.contains("hidden");
        notificationDropdown.classList.toggle("hidden", !shouldOpen);
    }

    function updateBadge(count) {
        if (!notificationBadge) return;
        if (count > 0) {
            notificationBadge.textContent = count;
            notificationBadge.style.display = "flex";
        } else {
            notificationBadge.style.display = "none";
        }
    }

    async function apiPost(url) {
        const headers = { "Content-Type": "application/json" };
        if (csrfToken) headers["x-csrf-token"] = csrfToken;
        return fetch(url, { method: "POST", headers });
    }

    notificationButton?.addEventListener("click", (e) => {
        e.stopPropagation();
        toggleDropdown();
    });

    document.addEventListener("click", (e) => {
        if (
            notificationDropdown &&
            notificationButton &&
            !notificationDropdown.contains(e.target) &&
            !notificationButton.contains(e.target)
        ) {
            toggleDropdown(false);
        }
    });

    document.querySelectorAll(".notification-read").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
            e.stopPropagation();
            const id = btn.dataset.notificationId;
            if (!id) return;
            const res = await apiPost(`/api/v1/notifications/${id}/mark-read`);
            if (res.ok) {
                const item = btn.closest(".notification-item");
                if (item) {
                    item.classList.remove(...unreadBorderClasses);
                    item.classList.add(...readBorderClasses);
                }
                btn.remove();
                const current = parseInt(notificationBadge?.textContent || "0", 10);
                updateBadge(Math.max(current - 1, 0));
                const headerBadge = document.querySelector(
                    "#notification-dropdown .bg-turf-green, #notification-dropdown .dark\\:bg-golden-bronze"
                );
                if (headerBadge) {
                    const newCount = Math.max(current - 1, 0);
                    if (newCount > 0) {
                        headerBadge.textContent = newCount;
                    } else {
                        headerBadge.remove();
                    }
                }
            }
        });
    });

    markAllBtn?.addEventListener("click", async () => {
        const res = await apiPost("/api/v1/notifications/mark-all-read");
        if (res.ok) {
            document.querySelectorAll(".notification-item").forEach((item) => {
                item.classList.remove(...unreadBorderClasses);
                item.classList.add(...readBorderClasses);
                item.querySelector(".notification-read")?.remove();
            });
            updateBadge(0);
            const headerBadge = document.querySelector(
                "#notification-dropdown .bg-turf-green, #notification-dropdown .dark\\:bg-golden-bronze"
            );
            headerBadge?.remove();
        }
    });

    // Toast helper
    function showToast(message, type = "info", duration = 4500) {
        const container = document.getElementById("toast-container");
        if (!container) {
            alert(message);
            return;
        }
        const colors = {
            success: "bg-green-100 text-green-900 border border-green-200",
            error: "bg-red-100 text-red-900 border border-red-200",
            warning: "bg-amber-100 text-amber-900 border border-amber-200",
            info: "bg-white text-carbon border border-gray-200 dark:bg-carbon-800 dark:text-parchment dark:border-carbon-700",
        };
        const icon = {
            success: "fa-circle-check",
            error: "fa-circle-xmark",
            warning: "fa-triangle-exclamation",
            info: "fa-circle-info",
        };
        const toast = document.createElement("div");
        toast.className = `pointer-events-auto shadow-xl rounded-lg px-4 py-3 flex items-start gap-3 ${colors[type] || colors.info}`;
        toast.innerHTML = `
            <div class="pt-0.5 text-lg"><i class="fa-solid ${icon[type] || icon.info}"></i></div>
            <div class="flex-1 text-sm leading-snug">${message}</div>
            <button class="text-gray-500 hover:text-gray-800 dark:text-parchment/80 dark:hover:text-parchment close-btn">
                <i class="fa-solid fa-xmark"></i>
            </button>
        `;
        const remove = () => {
            toast.classList.add("opacity-0", "-translate-y-2", "transition");
            setTimeout(() => toast.remove(), 200);
        };
        toast.querySelector(".close-btn")?.addEventListener("click", remove);
        container.appendChild(toast);
        setTimeout(remove, duration);
    }

    // Expose showToast globally for use by page scripts
    window.showToast = showToast;

    // Search Modal
    const searchToggle = document.getElementById("search-toggle");
    const searchOverlay = document.getElementById("search-overlay");
    const searchBackdrop = document.getElementById("search-backdrop");
    const searchClose = document.getElementById("search-close");
    const searchInput = document.getElementById("search-input");
    const adminHeader = document.querySelector(".admin-header");

    function positionSearchOverlay() {
        if (!searchOverlay) return;
        const headerRect = adminHeader?.getBoundingClientRect();
        const topOffset = (headerRect?.bottom ?? 96) + 12;
        searchOverlay.style.top = `${topOffset}px`;
    }

    function openSearch() {
        positionSearchOverlay();
        searchOverlay?.classList.remove("hidden");
        searchBackdrop?.classList.remove("hidden");
        setTimeout(() => searchInput?.focus(), 50);
    }

    function closeSearch() {
        searchOverlay?.classList.add("hidden");
        searchBackdrop?.classList.add("hidden");
    }

    searchToggle?.addEventListener("click", openSearch);
    searchClose?.addEventListener("click", closeSearch);
    searchBackdrop?.addEventListener("click", closeSearch);
    window.addEventListener("resize", () => {
        if (searchOverlay && !searchOverlay.classList.contains("hidden")) {
            positionSearchOverlay();
        }
    });

    document.addEventListener("keydown", (e) => {
        if (
            e.key === "Escape" &&
            searchOverlay &&
            !searchOverlay.classList.contains("hidden")
        ) {
            closeSearch();
        }
        if ((e.metaKey || e.ctrlKey) && e.key === "k") {
            e.preventDefault();
            if (searchOverlay?.classList.contains("hidden")) {
                openSearch();
            } else {
                closeSearch();
            }
        }
    });
})();
