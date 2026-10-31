// Package schemas holds the event contract shared by every service.
package schemas

import _ "embed"

//go:embed event.v1.json
var EventV1 []byte
