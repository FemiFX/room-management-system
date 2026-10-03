(function () {
    const openSidebarBtn = document.getElementById("openSidebar");
    const closeSidebarBtn = document.getElementById("closeSidebar");
    const mobileSidebar = document.getElementById("mobileSidebar");
    const sidebarOverlay = document.getElementById("sidebarOverlay");
    const htmlEl = document.documentElement;

    openSidebarBtn?.addEventListener("click", () => {
        mobileSidebar?.classList.remove("-translate-x-full");
        sidebarOverlay?.classList.remove("hidden");
    });

    closeSidebarBtn?.addEventListener("click", () => {
        mobileSidebar?.classList.add("-translate-x-full");
        sidebarOverlay?.classList.add("hidden");
    });

    sidebarOverlay?.addEventListener("click", () => {
        mobileSidebar?.classList.add("-translate-x-full");
        sidebarOverlay?.classList.add("hidden");
    });

    function ensureSidebarPanelVisible(btn, panel) {
        const scrollContainer = panel?.closest("nav");
        if (!scrollContainer) return;
        requestAnimationFrame(() => {
            const containerRect = scrollContainer.getBoundingClientRect();
            const panelRect = panel.getBoundingClientRect();
            const buttonRect = btn.getBoundingClientRect();
            const padding = 10;

            if (buttonRect.top < containerRect.top) {
                scrollContainer.scrollTop -=
                    containerRect.top - buttonRect.top + padding;
            }
            if (panelRect.bottom > containerRect.bottom) {
                scrollContainer.scrollTop +=
                    panelRect.bottom - containerRect.bottom + padding;
            }
        });
    }

    function closeSiblingSidebarPanels(btn, panel) {
        const scrollContainer = panel?.closest("nav");
        if (!scrollContainer) return;
        scrollContainer.querySelectorAll(".submenu.open").forEach((openPanel) => {
            if (openPanel === panel) return;
            openPanel.classList.remove("open");
            openPanel.style.display = "none";
            const toggleBtn = scrollContainer.querySelector(
                `[data-target="${openPanel.id}"]`
            );
            const toggleIcon = toggleBtn?.querySelector(".fa-chevron-down");
            toggleIcon?.classList.remove("rotate-180", "transform");
        });
    }

    // Sidebar accordion (desktop + mobile)
    document.querySelectorAll("[data-toggle]").forEach((btn) => {
        btn.addEventListener("click", (e) => {
            const desktopSidebar = document.getElementById("sidebar");
            const isDesktopSectionToggle = btn.classList.contains(
                "sidebar-toggle-item"
            );
            if (
                isDesktopSectionToggle &&
                desktopSidebar?.classList.contains("collapsed")
            ) {
                e.preventDefault();
                btn.blur();
                return;
            }
            const targetId = btn.getAttribute("data-target");
            const panel = document.getElementById(targetId);
            const icon = btn.querySelector(".fa-chevron-down");
            if (!panel) return;

            if (panel.classList.contains("open")) {
                panel.classList.remove("open");
                panel.style.display = "none";
                icon?.classList.remove("rotate-180", "transform");
            } else {
                closeSiblingSidebarPanels(btn, panel);
                panel.classList.add("open");
                panel.style.display = "block";
                icon?.classList.add("rotate-180", "transform");
                ensureSidebarPanelVisible(btn, panel);
            }
        });
    });

    // Sidebar collapse toggle
    const sidebar = document.getElementById("sidebar");
    const adminLayout = document.querySelector(".admin-layout");
    const sidebarCollapseBtn = document.getElementById("sidebarCollapseBtn");

    function setSidebarCollapsed(collapsed) {
        if (!sidebar || !adminLayout) return;
        sidebar.classList.toggle("collapsed", collapsed);
        adminLayout.classList.toggle("sidebar-collapsed", collapsed);
        localStorage.setItem("sidebarCollapsed", collapsed ? "true" : "false");
    }

    const storedSidebarState = localStorage.getItem("sidebarCollapsed");
    setSidebarCollapsed(storedSidebarState === "true");
    htmlEl.classList.add("sidebar-state-ready");
    htmlEl.classList.remove("sidebar-preload-collapsed");

    sidebarCollapseBtn?.addEventListener("click", () => {
        const isCollapsed = sidebar?.classList.contains("collapsed");
        setSidebarCollapsed(!isCollapsed);
    });

    // Viewport-aware flyout positioning for collapsed sidebar
    function positionCollapsedFlyout(group) {
        if (!sidebar?.classList.contains("collapsed")) return;
        const submenu = group.querySelector(":scope > .submenu");
        if (!submenu) return;
        const groupRect = group.getBoundingClientRect();
        const sidebarRect = sidebar.getBoundingClientRect();
        submenu.style.visibility = "hidden";
        submenu.style.display = "block";
        const submenuHeight = submenu.offsetHeight;
        submenu.style.display = "";
        submenu.style.visibility = "";
        let top = groupRect.top;
        if (top + submenuHeight > window.innerHeight - 8) {
            top = Math.max(8, window.innerHeight - submenuHeight - 8);
        }
        submenu.style.top = `${top}px`;
        submenu.style.left = `${sidebarRect.right}px`;
    }

    document.querySelectorAll(".sidebar-group-expandable").forEach((group) => {
        let leaveTimer = null;
        group.addEventListener("mouseenter", () => {
            if (leaveTimer) {
                clearTimeout(leaveTimer);
                leaveTimer = null;
            }
            positionCollapsedFlyout(group);
            group.classList.add("hovered");
        });
        group.addEventListener("mouseleave", () => {
            leaveTimer = setTimeout(() => {
                group.classList.remove("hovered");
                leaveTimer = null;
            }, 150);
        });
        const submenu = group.querySelector(":scope > .submenu");
        if (submenu) {
            submenu.addEventListener("mouseenter", () => {
                if (leaveTimer) {
                    clearTimeout(leaveTimer);
                    leaveTimer = null;
                }
                group.classList.add("hovered");
            });
            submenu.addEventListener("mouseleave", () => {
                leaveTimer = setTimeout(() => {
                    group.classList.remove("hovered");
                    leaveTimer = null;
                }, 150);
            });
        }
    });

    // Tooltip for single (non-expandable) sidebar items in collapsed mode
    const sidebarTooltip = document.getElementById("sidebar-item-tooltip");
    if (sidebarTooltip) {
        document
            .querySelectorAll(
                ".sidebar-group:not(.sidebar-group-expandable) .sidebar-item"
            )
            .forEach((item) => {
                item.addEventListener("mouseenter", () => {
                    if (!sidebar?.classList.contains("collapsed")) return;
                    const label = item.dataset.tooltip;
                    if (!label) return;
                    sidebarTooltip.textContent = label;
                    const rect = item.getBoundingClientRect();
                    const sidebarRect = sidebar.getBoundingClientRect();
                    sidebarTooltip.style.top = `${rect.top + rect.height / 2}px`;
                    sidebarTooltip.style.left = `${sidebarRect.right + 12}px`;
                    sidebarTooltip.style.transform = "translateY(-50%)";
                    sidebarTooltip.classList.add("visible");
                });
                item.addEventListener("mouseleave", () => {
                    sidebarTooltip.classList.remove("visible");
                });
            });
    }

    // Auto-scroll sidebar to active item on page load
    const sidebarNav = sidebar?.querySelector("nav");
    const activeSubItem = sidebarNav?.querySelector(".submenu a.active");
    const activeSingleItem = sidebarNav?.querySelector("a.sidebar-item.active");
    if (activeSubItem && sidebarNav) {
        const activePanel = activeSubItem.closest(".submenu");
        const activeToggleBtn = activePanel?.id
            ? sidebarNav.querySelector(`[data-target="${activePanel.id}"]`)
            : null;
        if (activePanel && activeToggleBtn) {
            ensureSidebarPanelVisible(activeToggleBtn, activePanel);
        } else {
            activeSubItem.scrollIntoView({ block: "nearest" });
        }
    } else if (activeSingleItem && sidebarNav) {
        activeSingleItem.scrollIntoView({ block: "nearest" });
    }
})();
