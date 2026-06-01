# Migration Verification Checklist

## Quick Verification Commands

### 1. Check All Migrated Files Exist
```bash
# Core layout and pages
ls -la src/app/layout/DesktopLayout.tsx
ls -la src/app/pages/{AuthView,DashboardView,AlertsView,SettingsView}.tsx
ls -la src/app/components/WindowTitleBar.tsx
ls -la src/app/services/api.ts

# UI Components
ls src/components/ui/ | wc -l  # Should show 49
ls src/components/figma/

# Styles
ls -la src/styles/{index,tailwind,theme}.css

# Assets
ls public/fonts/ | head -5
ls src/logo/
```

### 2. Verify Import Paths
```bash
# Check that all imports use @ alias
grep -r "from '@/" src/app/pages/ | wc -l  # Should be > 0
grep -r "from '\.\./\.\./\.\." src/app/pages/ | wc -l  # Should be 0

# Check UI components use @/lib/utils
grep -r "from '@/lib/utils'" src/components/ui/ | wc -l  # Should be 5
```

### 3. Check Dependencies
```bash
# Verify all packages installed
npm list @emotion/react @mui/material recharts sonner tw-animate-css
```

### 4. File Count Verification
```bash
echo "UI Components: $(ls src/components/ui/*.tsx 2>/dev/null | wc -l)"
echo "Pages: $(ls src/app/pages/*.tsx 2>/dev/null | wc -l)"
echo "Fonts: $(ls public/fonts/*.woff2 2>/dev/null | wc -l)"
```

---

## Manual Testing Checklist

### Authentication Flow
- [ ] Navigate to `http://localhost:5173/login`
- [ ] UI matches Electron app (glassmorphism, gold theme)
- [ ] Theme toggle works (light/dark)
- [ ] Language toggle works (English/Persian)
- [ ] Login form validation works
- [ ] Successful login redirects to dashboard
- [ ] Invalid credentials show error toast

### Dashboard View
- [ ] Dashboard loads with correct layout
- [ ] Sidebar is visible with navigation items
- [ ] Price cards display correctly
- [ ] Charts render with Recharts
- [ ] Theme toggle works
- [ ] Language toggle works
- [ ] Logout button works

### Layout & Navigation
- [ ] Sidebar navigation works (Dashboard, Alerts, Settings)
- [ ] Sidebar collapse/expand works
- [ ] WindowTitleBar is hidden (no Electron controls visible)
- [ ] Mobile responsive behavior works
- [ ] RTL layout works for Persian language

### Styling & Theme
- [ ] Dark mode applies correctly
- [ ] Light mode applies correctly
- [ ] Glassmorphism effects visible
- [ ] Gold accent colors match design
- [ ] Vazir font loads correctly
- [ ] Smooth theme transitions work
- [ ] Custom scrollbar styling works

### PWA Features
- [ ] Service worker registers successfully
- [ ] App can be installed as PWA
- [ ] Offline functionality works (if implemented)
- [ ] Manifest.json loads correctly

---

## Common Issues & Solutions

### Issue: "Cannot find module '@/...'"
**Solution:** Check `vite.config.ts` has the alias configured:
```typescript
resolve: {
  alias: {
    '@': path.resolve(__dirname, './src')
  }
}
```

### Issue: Fonts not loading
**Solution:** Verify fonts are in `public/fonts/` and CSS paths use `/fonts/` (not `./fonts/`)

### Issue: Theme not applying
**Solution:** Check `AppProvider` wraps the entire app in `App.tsx`

### Issue: Authentication not persisting
**Solution:** Verify `localStorage` is being used in `AppContext.tsx`

### Issue: API calls failing
**Solution:** Set `VITE_API_URL` in `.env` file or verify backend is running

---

## Build Verification

### Development Build
```bash
npm run dev
# Should start without errors
# Check console for any warnings
```

### Production Build
```bash
npm run build
# Should complete without TypeScript errors
# Check dist/ folder is created
```

### Preview Production Build
```bash
npm run preview
# Should serve the built app
# Test all features in production mode
```

---

## Success Criteria

✅ All 6 migration phases completed
✅ No TypeScript compilation errors
✅ No console errors on page load
✅ Authentication flow works end-to-end
✅ UI matches Electron app pixel-perfectly
✅ Theme and language switching works
✅ All routes accessible and functional
✅ PWA infrastructure intact

---

## Rollback Plan (if needed)

If critical issues are found:
1. Revert to previous commit: `git reset --hard HEAD~1`
2. Or restore from backup: `git stash` before migration
3. Check `MIGRATION_SUMMARY.md` for specific file changes to revert

---

## Performance Benchmarks

Expected metrics:
- Initial page load: < 2s
- Route transitions: < 100ms
- Theme toggle: < 50ms
- API response time: < 500ms (depends on backend)

Monitor with:
```bash
# Lighthouse audit
npm run build && npm run preview
# Then run Lighthouse in Chrome DevTools
```

---

## Next Development Steps

After verification passes:
1. Add unit tests for migrated components
2. Add E2E tests for critical flows
3. Optimize bundle size if needed
4. Add error boundaries
5. Implement analytics tracking
6. Set up CI/CD pipeline
7. Deploy to staging environment

