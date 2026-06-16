// TBCA Explorer - Core Logic Application

// Global state
let foodsData = [];
let filteredFoods = [];
let foodClasses = new Set();
let currentPage = 1;
const itemsPerPage = 24;

// DOM Elements
const searchInput = document.getElementById('search-input');
const clearSearchBtn = document.getElementById('clear-search-btn');
const classFilter = document.getElementById('class-filter');
const sortSelect = document.getElementById('sort-select');
const foodsGrid = document.getElementById('foods-grid');
const emptyState = document.getElementById('empty-state');
const resetFiltersBtn = document.getElementById('reset-filters-btn');
const totalFoodsCount = document.getElementById('total-foods-count');
const resultsTitle = document.getElementById('results-title');

// Pagination Elements
const paginationContainer = document.getElementById('pagination');
const prevPageBtn = document.getElementById('prev-page-btn');
const nextPageBtn = document.getElementById('next-page-btn');
const pageInfo = document.getElementById('page-info');

// Modal Elements
const nutrientModal = document.getElementById('nutrient-modal');
const closeModalBtn = document.getElementById('close-modal-btn');
const modalFoodCode = document.getElementById('modal-food-code');
const modalFoodClass = document.getElementById('modal-food-class');
const modalFoodTitle = document.getElementById('modal-title');
const macroEnergy = document.getElementById('macro-energy');
const macroCarbs = document.getElementById('macro-carbs');
const macroProteins = document.getElementById('macro-proteins');
const macroFats = document.getElementById('macro-fats');
const macroFibers = document.getElementById('macro-fibers');
const barCarbs = document.getElementById('bar-carbs');
const barProteins = document.getElementById('bar-proteins');
const barFats = document.getElementById('bar-fats');
const barFibers = document.getElementById('bar-fibers');
const tabButtons = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');

// Initialize App
document.addEventListener('DOMContentLoaded', () => {
    loadData();
    setupEventListeners();
});

// Fetch food data
async function loadData() {
    try {
        // Fetch optimized JSON
        const response = await fetch('alimentos.json');
        if (!response.ok) {
            throw new Error('Erro ao carregar banco de dados local da TBCA.');
        }
        foodsData = await response.json();
        
        // Populate classes list
        foodsData.forEach(food => {
            if (food.g) foodClasses.add(food.g);
        });
        
        // Populate classes select
        populateClassDropdown();
        
        // Initial setup
        filteredFoods = [...foodsData];
        totalFoodsCount.textContent = foodsData.length.toLocaleString('pt-BR');
        
        // Render
        updateList();
        
    } catch (error) {
        console.error(error);
        foodsGrid.innerHTML = `
            <div class="empty-state" style="grid-column: 1/-1;">
                <div class="empty-icon" style="color: var(--accent-red);">⚠️</div>
                <h3>Erro ao carregar dados</h3>
                <p>${error.message}</p>
                <p>Verifique se o arquivo alimentos.json está no mesmo diretório do index.html.</p>
            </div>
        `;
    }
}

// Populate classes filter dropdown
function populateClassDropdown() {
    // Sort classes alphabetically
    const sortedClasses = Array.from(foodClasses).sort((a, b) => a.localeCompare(b, 'pt-BR'));
    sortedClasses.forEach(className => {
        const option = document.createElement('option');
        option.value = className;
        option.textContent = className;
        classFilter.appendChild(option);
    });
}

// Setup Event Listeners
function setupEventListeners() {
    // Search input
    searchInput.addEventListener('input', () => {
        const query = searchInput.value.trim();
        clearSearchBtn.style.display = query.length > 0 ? 'block' : 'none';
        currentPage = 1;
        applyFilters();
    });

    // Clear search
    clearSearchBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearSearchBtn.style.display = 'none';
        searchInput.focus();
        currentPage = 1;
        applyFilters();
    });

    // Class filter
    classFilter.addEventListener('change', () => {
        currentPage = 1;
        applyFilters();
    });

    // Sort selection
    sortSelect.addEventListener('change', () => {
        applySorting();
        currentPage = 1;
        renderFoods();
    });

    // Reset filters button (in empty state)
    resetFiltersBtn.addEventListener('click', () => {
        searchInput.value = '';
        clearSearchBtn.style.display = 'none';
        classFilter.value = 'all';
        sortSelect.value = 'descricao';
        currentPage = 1;
        applyFilters();
    });

    // Pagination
    prevPageBtn.addEventListener('click', () => {
        if (currentPage > 1) {
            currentPage--;
            renderFoods();
            scrollToTop();
        }
    });

    nextPageBtn.addEventListener('click', () => {
        const totalPages = Math.ceil(filteredFoods.length / itemsPerPage);
        if (currentPage < totalPages) {
            currentPage++;
            renderFoods();
            scrollToTop();
        }
    });

    // Close modal actions
    closeModalBtn.addEventListener('click', closeModal);
    nutrientModal.addEventListener('click', (e) => {
        if (e.target === nutrientModal) closeModal();
    });
    
    // Modal tabs toggle
    tabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            tabButtons.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.remove('active'));
            
            btn.classList.add('active');
            const targetId = btn.getAttribute('data-tab');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // Keyboard support (Escape to close modal)
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && nutrientModal.classList.contains('active')) {
            closeModal();
        }
    });
}

// Scroll to main panel top
function scrollToTop() {
    document.querySelector('.app-main').scrollTo({
        top: 0,
        behavior: 'smooth'
    });
}

// Filter and sort items
function applyFilters() {
    const query = searchInput.value.toLowerCase().trim();
    const selectedClass = classFilter.value;

    // Filter by search term & class selection
    filteredFoods = foodsData.filter(food => {
        const matchesQuery = !query || 
            food.d.toLowerCase().includes(query) || 
            food.c.toLowerCase().includes(query);
            
        const matchesClass = selectedClass === 'all' || food.g === selectedClass;
        
        return matchesQuery && matchesClass;
    });

    // Sort items
    applySorting();
    
    // Render list
    updateList();
}

// Apply sorting to filtered list
function applySorting() {
    const sortBy = sortSelect.value;
    
    filteredFoods.sort((a, b) => {
        switch (sortBy) {
            case 'codigo':
                return a.c.localeCompare(b.c);
                
            case 'kcal-desc':
                return (b.n['Energia (kcal)'] || 0) - (a.n['Energia (kcal)'] || 0);
                
            case 'kcal-asc':
                return (a.n['Energia (kcal)'] || 0) - (b.n['Energia (kcal)'] || 0);
                
            case 'proteina-desc':
                return (b.n['Proteína (g)'] || 0) - (a.n['Proteína (g)'] || 0);
                
            case 'descricao':
            default:
                return a.d.localeCompare(b.d, 'pt-BR');
        }
    });
}

// Update list counter and render cards
function updateList() {
    const totalCount = filteredFoods.length;
    resultsTitle.textContent = queryActive() 
        ? `${totalCount} alimento(s) encontrado(s)` 
        : `Todos os Alimentos (${totalCount})`;
        
    if (totalCount === 0) {
        foodsGrid.style.display = 'none';
        paginationContainer.style.display = 'none';
        emptyState.style.display = 'flex';
    } else {
        emptyState.style.display = 'none';
        foodsGrid.style.display = 'grid';
        paginationContainer.style.display = 'flex';
        renderFoods();
    }
}

// Check if any query or class filter is active
function queryActive() {
    return searchInput.value.trim().length > 0 || classFilter.value !== 'all';
}

// Render paginated cards
function renderFoods() {
    foodsGrid.innerHTML = '';
    
    const startIndex = (currentPage - 1) * itemsPerPage;
    const endIndex = Math.min(startIndex + itemsPerPage, filteredFoods.length);
    const paginatedItems = filteredFoods.slice(startIndex, endIndex);
    
    const query = searchInput.value.trim();
    
    paginatedItems.forEach(food => {
        const card = document.createElement('div');
        card.className = 'food-card';
        card.setAttribute('tabindex', '0');
        card.setAttribute('role', 'button');
        
        // Highlight terms
        let nameHTML = food.d;
        if (query) {
            const regex = new RegExp(`(${escapeRegExp(query)})`, 'gi');
            nameHTML = food.d.replace(regex, '<mark class="search-highlight">$1</mark>');
        }
        
        // Macro stats values (fallback to 0 or trace)
        const kcal = food.n['Energia (kcal)'] !== undefined ? food.n['Energia (kcal)'] : '-';
        const carb = food.n['Carboidrato total (g)'] !== undefined ? food.n['Carboidrato total (g)'] : '-';
        const prot = food.n['Proteína (g)'] !== undefined ? food.n['Proteína (g)'] : '-';
        const fat = food.n['Lipídios (g)'] !== undefined ? food.n['Lipídios (g)'] : '-';
        
        card.innerHTML = `
            <div class="card-header-info">
                <span class="card-code">${food.c}</span>
                <span class="card-class" title="${food.g}">${food.g}</span>
            </div>
            <h3>${nameHTML}</h3>
            <div class="card-macros">
                <div class="card-macro-item">
                    <span class="card-macro-val cal">${kcal}</span>
                    <span class="card-macro-label">kcal</span>
                </div>
                <div class="card-macro-item">
                    <span class="card-macro-val carb">${carb}g</span>
                    <span class="card-macro-label">Carbs</span>
                </div>
                <div class="card-macro-item">
                    <span class="card-macro-val prot">${prot}g</span>
                    <span class="card-macro-label">Prot</span>
                </div>
                <div class="card-macro-item">
                    <span class="card-macro-val lip">${fat}g</span>
                    <span class="card-macro-label">Lip</span>
                </div>
            </div>
        `;
        
        // Event listeners for card details
        card.addEventListener('click', () => showDetails(food));
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                showDetails(food);
            }
        });
        
        foodsGrid.appendChild(card);
    });
    
    updatePaginationControls();
}

// Update Pagination panel buttons state
function updatePaginationControls() {
    const totalPages = Math.ceil(filteredFoods.length / itemsPerPage) || 1;
    pageInfo.textContent = `Página ${currentPage} de ${totalPages}`;
    
    prevPageBtn.disabled = currentPage === 1;
    nextPageBtn.disabled = currentPage === totalPages;
}

// Show food nutrient details in modal
function showDetails(food) {
    modalFoodCode.textContent = food.c;
    modalFoodClass.textContent = food.g;
    modalFoodTitle.textContent = food.d;
    
    // Quick macros values
    const kcal = food.n['Energia (kcal)'] !== undefined ? food.n['Energia (kcal)'] : '0';
    const carb = food.n['Carboidrato total (g)'] !== undefined ? food.n['Carboidrato total (g)'] : 0;
    const prot = food.n['Proteína (g)'] !== undefined ? food.n['Proteína (g)'] : 0;
    const fat = food.n['Lipídios (g)'] !== undefined ? food.n['Lipídios (g)'] : 0;
    const fiber = food.n['Fibra alimentar (g)'] !== undefined ? food.n['Fibra alimentar (g)'] : 0;
    
    macroEnergy.textContent = kcal;
    macroCarbs.textContent = typeof carb === 'number' ? `${carb}g` : carb;
    macroProteins.textContent = typeof prot === 'number' ? `${prot}g` : prot;
    macroFats.textContent = typeof fat === 'number' ? `${fat}g` : fat;
    macroFibers.textContent = typeof fiber === 'number' ? `${fiber}g` : fiber;
    
    // Animate macro progress bars (max value representation: grams in 100g max weight is 100%)
    // But fiber is generally small, so let's scale it to max 30g for visible bar representation
    barCarbs.style.width = typeof carb === 'number' ? `${Math.min(carb, 100)}%` : '0%';
    barProteins.style.width = typeof prot === 'number' ? `${Math.min(prot, 100)}%` : '0%';
    barFats.style.width = typeof fat === 'number' ? `${Math.min(fat, 100)}%` : '0%';
    barFibers.style.width = typeof fiber === 'number' ? `${Math.min((fiber / 30) * 100, 100)}%` : '0%';
    
    // Build tables
    buildNutrientGrids(food);
    
    // Reset active tab to first tab
    document.getElementById('tab-btn-all').click();
    
    // Show Modal
    nutrientModal.classList.add('active');
    nutrientModal.setAttribute('aria-hidden', 'false');
    document.body.style.overflow = 'hidden'; // prevent page scroll background
    closeModalBtn.focus();
}

// Build list grids for modal tabs
function buildNutrientGrids(food) {
    const allGrid = document.getElementById('all-nutrients-grid');
    const mineralsGrid = document.getElementById('minerals-nutrients-grid');
    const vitaminsGrid = document.getElementById('vitamins-nutrients-grid');
    const fatsGrid = document.getElementById('fats-nutrients-grid');
    
    // Clear grids
    allGrid.innerHTML = '';
    mineralsGrid.innerHTML = '';
    vitaminsGrid.innerHTML = '';
    fatsGrid.innerHTML = '';
    
    // Lists definition
    const mineralsList = ["cálcio", "ferro", "sódio", "magnésio", "fósforo", "potássio", "zinco", "cobre", "selênio"];
    const vitaminsList = ["vitamina", "alfa-tocoferol", "tiamina", "riboflavina", "niacina", "folato"];
    const fatsList = ["graxos", "colesterol"];
    
    // Sort nutrients key list
    const sortedKeys = Object.keys(food.n).sort((a, b) => a.localeCompare(b, 'pt-BR'));
    
    sortedKeys.forEach(key => {
        // Extract component name and unit
        const match = key.match(/(.*) \((.*)\)/);
        const name = match ? match[1] : key;
        const unit = match ? match[2] : '';
        const value = food.n[key];
        
        const cardHTML = `
            <div class="nutrient-card">
                <span class="nutrient-name" title="${name}">${name}</span>
                <span class="nutrient-value">${value}<span>${unit}</span></span>
            </div>
        `;
        
        // Append to All
        allGrid.insertAdjacentHTML('beforeend', cardHTML);
        
        // Categorize
        const lowerName = name.toLowerCase();
        
        if (mineralsList.some(item => lowerName.includes(item))) {
            mineralsGrid.insertAdjacentHTML('beforeend', cardHTML);
        } else if (vitaminsList.some(item => lowerName.includes(item))) {
            vitaminsGrid.insertAdjacentHTML('beforeend', cardHTML);
        } else if (fatsList.some(item => lowerName.includes(item))) {
            fatsGrid.insertAdjacentHTML('beforeend', cardHTML);
        }
    });
    
    // Add empty states for category tabs if empty
    checkEmptyCategoryGrid(mineralsGrid, "Nenhum mineral registrado para este alimento.");
    checkEmptyCategoryGrid(vitaminsGrid, "Nenhuma vitamina registrada para este alimento.");
    checkEmptyCategoryGrid(fatsGrid, "Nenhum lipídeo ou ácido graxo registrado.");
}

function checkEmptyCategoryGrid(gridElement, message) {
    if (gridElement.children.length === 0) {
        gridElement.innerHTML = `
            <div class="empty-category" style="grid-column: 1/-1; padding: 2rem; text-align: center; color: var(--text-muted); font-size: 0.875rem;">
                ${message}
            </div>
        `;
    }
}

// Close Modal
function closeModal() {
    nutrientModal.classList.remove('active');
    nutrientModal.setAttribute('aria-hidden', 'true');
    document.body.style.overflow = ''; // restore scroll
    searchInput.focus();
}

// Helper to escape regular expressions
function escapeRegExp(string) {
    return string.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
