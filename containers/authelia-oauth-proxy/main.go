package main

import (
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"
)

const (
	autheliaURL  = "http://authelia-app:9091"
	proxyPort    = ":8080"
	groupsScope  = "groups"
)

func main() {
	// Parse upstream Authelia URL
	upstream, err := url.Parse(autheliaURL)
	if err != nil {
		log.Fatalf("Failed to parse upstream URL: %v", err)
	}

	// Create reverse proxy
	proxy := httputil.NewSingleHostReverseProxy(upstream)

	// Customize director to modify OAuth authorization requests
	originalDirector := proxy.Director
	proxy.Director = func(req *http.Request) {
		originalDirector(req)

		// Only modify OAuth authorization endpoint requests
		if strings.HasPrefix(req.URL.Path, "/api/oidc/authorization") {
			query := req.URL.Query()

			// Check if scope parameter exists
			if scope := query.Get("scope"); scope != "" {
				// Add groups scope if not already present
				if !strings.Contains(scope, groupsScope) {
					query.Set("scope", scope+" "+groupsScope)
					req.URL.RawQuery = query.Encode()
					log.Printf("Injected groups scope for request from %s", req.RemoteAddr)
				}
			}
		}
	}

	// Health check endpoint
	http.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("OK"))
	})

	// All other requests go through the proxy
	http.Handle("/", proxy)

	log.Printf("OAuth scope injection proxy listening on %s", proxyPort)
	log.Printf("Proxying to %s", autheliaURL)
	if err := http.ListenAndServe(proxyPort, nil); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}
