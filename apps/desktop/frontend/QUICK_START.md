# Quick Start Guide

## Running the Application

```bash
cd /mnt/c/dev/Nerkhbaan-app/frontend
npm install  # if not already installed
npm run dev
```

The app will start at `http://localhost:5173`

## First Time Setup

1. **Clear Browser Cache** (important!)
   - Press `Ctrl+Shift+Delete` (Chrome/Edge)
   - Clear cached images and files
   - Or use incognito/private mode

2. **Clear localStorage** (if you have old tokens)
   - Open DevTools (F12)
   - Go to Application > Local Storage
   - Delete `authToken` if it exists

## Login Flow

1. Navigate to `http://localhost:5173`
2. You'll be redirected to `/auth` (login page)
3. Enter any credentials (demo mode)
4. Click "ورود به حساب" (Sign In)
5. You'll be redirected to dashboard

## Features to Test

### Dashboard (`/`)
- 4 asset cards (Gold, USD, Bitcoin, Silver)
- Live price charts
- Quick alert buttons (hover over cards)
- Click "هشدار سریع" to create alert

### Alerts (`/alerts`)
- View all configured alerts
- Toggle alerts on/off
- Edit/delete alerts
- Search functionality

### Settings (`/settings`)
- Toggle dark/light theme
- Switch language (Persian ⟷ English)
- Configure notification channels
- Adjust app behavior

### Global Features
- **Theme Toggle:** Click moon/sun icon in header
- **Language Toggle:** Click language button in header
- **Notifications:** Bell icon shows notification dropdown
- **Logout:** Click logout button in sidebar

## Troubleshooting

### Blank White Screen
- Check browser console (F12) for errors
- Verify all fixes were applied correctly
- Clear browser cache and localStorage
- Restart dev server

### Font Not Loading
- Check Network tab in DevTools
- Verify `/fonts/Vazir-Regular.woff2` returns 200 (not 404)
- Check `public/fonts/` directory exists

### Components Not Styled
- Verify `tailwind.config.js` exists
- Check `src/styles/index.css` imports Tailwind directives
- Restart dev server after config changes

### Authentication Loop
- Clear localStorage: `localStorage.clear()`
- Check `authToken` is being set correctly
- Verify `isAuthenticated` state in React DevTools

## Development Tips

### Hot Module Replacement (HMR)
- Changes to `.tsx` files reload automatically
- CSS changes apply instantly
- Context changes may require full reload

### React DevTools
- Install React DevTools extension
- Inspect `AppContext` state
- Check component tree for proper nesting

### Checking Context State
```javascript
// In browser console
localStorage.getItem('authToken')  // Check if token exists
```

## File Structure Reference

```
src/
├── main.tsx              # Entry point, AppProvider wrapper
├── app/
│   ├── App.tsx           # RouterProvider only
│   ├── routes.tsx        # Route definitions
│   ├── context/
│   │   └── AppContext.tsx  # Global state (auth, theme, i18n)
│   ├── layouts/
│   │   └── DesktopLayout.tsx  # Main layout with sidebar
│   └── views/
│       ├── AuthView.tsx      # Login page
│       ├── DashboardView.tsx # Main dashboard
│       ├── AlertsView.tsx    # Alerts management
│       └── SettingsView.tsx  # Settings page
└── styles/
    └── index.css         # Tailwind + font declarations
```

## Common Commands

```bash
# Development
npm run dev

# Build for production
npm run build

# Preview production build
npm run preview

# Type checking
npx tsc --noEmit
```

## Browser Support

- Chrome/Edge: ✓ Full support
- Firefox: ✓ Full support
- Safari: ✓ Full support (may need -webkit- prefixes)

## Performance Notes

- Initial load: ~2-3s (includes fonts, charts)
- Route transitions: Instant (client-side routing)
- Theme switching: Instant (CSS class toggle)
- Language switching: Instant (context update)

## Next Steps

After verifying the app works:
1. Connect to real backend API
2. Replace demo authentication with real auth
3. Add real-time price updates (WebSocket)
4. Implement actual alert notifications
5. Add user profile management
6. Set up production deployment

## Support

If issues persist after applying all fixes:
1. Check `FIXES_APPLIED.md` for detailed fix information
2. Verify all modified files match the patches
3. Ensure no merge conflicts exist
4. Check Node.js version (should be 18+)
5. Try deleting `node_modules` and reinstalling
