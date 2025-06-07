"use client"

import type React from "react"

import { useState, useEffect, useRef, type FormEvent } from "react"
import { useChat, type Message } from "ai/react"
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ScrollArea } from "@/components/ui/scroll-area"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import {
  Send,
  Sparkles,
  ChevronRight,
  ChevronDown,
  File,
  Folder,
  Code,
  Monitor,
  Zap,
  Rocket,
  Globe,
  ArrowRight,
  Play,
} from "lucide-react"

// --- Type Definitions ---
type FileNode = {
  path: string
  content: string
  oldContent?: string
}

// --- Main Page Component ---
export default function AIWebsiteBuilder() {
  const [isBuilding, setIsBuilding] = useState(false)
  const [files, setFiles] = useState<Map<string, FileNode>>(new Map())
  const [selectedFile, setSelectedFile] = useState<string>("")
  const [isLive, setIsLive] = useState(false)
  const [aiResponse, setAiResponse] = useState("")
  const websocketRef = useRef<WebSocket | null>(null)
  const { messages, input, handleInputChange, handleSubmit: useChatSubmit, setMessages, setInput } = useChat()

  const backendUrl = process.env.NEXT_PUBLIC_BACKEND_URL || "http://127.0.0.1:8000"
  const clonedAppUrl = `${backendUrl}/preview/`

  const handleReset = () => {
    if (websocketRef.current) {
      websocketRef.current.close()
      websocketRef.current = null
    }
    setIsBuilding(false)
    setFiles(new Map())
    setSelectedFile("")
    setIsLive(false)
    setAiResponse("")
    setMessages([])
  }

  const handleClone = (url: string) => {
    setIsBuilding(true)

    const wsUrl = backendUrl.replace(/^http/, "ws")
    const ws = new WebSocket(`${wsUrl}/ws/clone`)
    websocketRef.current = ws

    ws.onopen = () => {
      ws.send(JSON.stringify({ url }))
    }

    ws.onmessage = (event) => {
      const parsedEvent = JSON.parse(event.data)
      const { event: eventType, data } = parsedEvent

      if (eventType === "log") {
        if (aiResponse) {
          setMessages((prev) => [...prev, { id: Date.now().toString(), role: "assistant", content: aiResponse }])
          setAiResponse("")
        }
        setMessages((prev) => [...prev, { id: Date.now().toString(), role: "assistant", content: data.message }])
      } else if (eventType === "ai_token") {
        setAiResponse((prev) => prev + data.token)
      } else if (eventType === "file_create" || eventType === "file_update") {
        setFiles((prev) => {
          const newFiles = new Map(prev)
          newFiles.set(data.path, {
            path: data.path,
            content: data.content,
            oldContent: eventType === "file_update" ? data.old_content : prev.get(data.path)?.content,
          })
          return newFiles
        })
        if (!selectedFile) setSelectedFile(data.path)
      } else if (eventType === "status" && data.status === "ready") {
        setIsLive(true)
        if (aiResponse) {
          setMessages((prev) => [...prev, { id: Date.now().toString(), role: "assistant", content: aiResponse }])
          setAiResponse("")
        }
      }
    }

    ws.onerror = (err) => {
      console.error("WebSocket error:", err)
    }

    ws.onclose = () => {
      if (aiResponse) {
        setMessages((prev) => [...prev, { id: Date.now().toString(), role: "assistant", content: aiResponse }])
        setAiResponse("")
      }
    }
  }

  const handleInitialSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (input.trim()) {
      setMessages((prev) => [...prev, { id: Date.now().toString(), role: "user", content: input }])
    }

    const urlRegex = /(https?:\/\/[^\s]+)/
    const foundUrl = input.match(urlRegex)

    if (foundUrl) {
      handleClone(foundUrl[0])
    } else {
      handleClone("https://vercel.com/templates/next.js/nextjs-boilerplate")
      setMessages((prev) => [
        ...prev,
        {
          id: Date.now().toString(),
          role: "assistant",
          content: "No URL detected. Cloning a default Next.js boilerplate from Vercel as an example.",
        },
      ])
    }
    setInput("")
  }

  const handleModificationSubmit = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (!input.trim() || !websocketRef.current || websocketRef.current.readyState !== WebSocket.OPEN) return

    const userMessage = input
    setMessages((prev) => [...prev, { id: Date.now().toString(), role: "user", content: userMessage }])

    websocketRef.current.send(
      JSON.stringify({
        type: "modification",
        prompt: userMessage,
      }),
    )

    setInput("")
  }

  const currentFileContent = files.get(selectedFile)?.content || ""

  const displayedMessages: Message[] = [...messages]
  if (aiResponse) {
    displayedMessages.push({ id: "ai-streaming", role: "assistant", content: aiResponse })
  }

  if (isBuilding) {
    return (
      <div className="h-screen w-screen overflow-hidden bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900">
        <PanelGroup direction="horizontal" className="h-full w-full">
          <Panel defaultSize={30} minSize={25} className="min-w-[450px] flex flex-col overflow-hidden">
            <ChatInterface
              messages={displayedMessages}
              onReset={handleReset}
              input={input}
              handleInputChange={handleInputChange}
              handleSubmit={handleModificationSubmit}
            />
          </Panel>
          <PanelResizeHandle className="w-2 bg-gradient-to-b from-purple-500/20 to-blue-500/20 hover:from-purple-500/40 hover:to-blue-500/40 transition-all duration-300" />
          <Panel defaultSize={70} minSize={30} className="flex flex-col overflow-hidden">
            <MainPanel
              isLive={isLive}
              url={clonedAppUrl}
              files={files}
              selectedFile={selectedFile}
              onFileSelect={setSelectedFile}
              fileContent={currentFileContent}
            />
          </Panel>
        </PanelGroup>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-purple-900 to-slate-900 text-white relative overflow-hidden">
      {/* Animated background elements */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute -top-40 -right-40 w-80 h-80 bg-purple-500 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-pulse"></div>
        <div className="absolute -bottom-40 -left-40 w-80 h-80 bg-blue-500 rounded-full mix-blend-multiply filter blur-xl opacity-20 animate-pulse animation-delay-2000"></div>
        <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 w-96 h-96 bg-gradient-to-r from-purple-400 to-pink-400 rounded-full mix-blend-multiply filter blur-3xl opacity-10 animate-spin-slow"></div>
      </div>

      <div className="relative z-10 flex flex-col items-center justify-center min-h-screen px-4">
        {/* Logo and branding */}
        <div className="mb-8 text-center">
          <div className="inline-flex items-center justify-center w-20 h-20 mb-6 bg-gradient-to-r from-purple-500 to-pink-500 rounded-2xl shadow-2xl">
            <Zap className="w-10 h-10 text-white" />
          </div>
          <h1 className="text-6xl font-bold mb-4 bg-gradient-to-r from-white via-purple-200 to-pink-200 bg-clip-text text-transparent">
            Orchids AI
          </h1>
          <p className="text-xl text-gray-300 mb-2">The Future of Web Development</p>
          <p className="text-gray-400 max-w-2xl mx-auto leading-relaxed">
            Transform any website into a fully customizable, AI-powered experience. Clone, modify, and deploy with the
            power of artificial intelligence.
          </p>
        </div>

        {/* Feature badges */}
        <div className="flex flex-wrap gap-3 mb-8 justify-center">
          <Badge variant="secondary" className="bg-purple-500/20 text-purple-200 border-purple-500/30 px-4 py-2">
            <Rocket className="w-4 h-4 mr-2" />
            Instant Cloning
          </Badge>
          <Badge variant="secondary" className="bg-blue-500/20 text-blue-200 border-blue-500/30 px-4 py-2">
            <Sparkles className="w-4 h-4 mr-2" />
            AI-Powered
          </Badge>
          <Badge variant="secondary" className="bg-pink-500/20 text-pink-200 border-pink-500/30 px-4 py-2">
            <Globe className="w-4 h-4 mr-2" />
            Live Preview
          </Badge>
        </div>

        {/* Main input form */}
        <div className="w-full max-w-2xl mb-12">
          <form onSubmit={handleInitialSubmit} className="relative">
            <div className="relative group">
              <Input
                value={input}
                onChange={handleInputChange}
                placeholder="Enter a website URL to clone, or describe what you want to build..."
                className="w-full h-16 px-6 pr-16 text-lg bg-white/10 backdrop-blur-md border-white/20 text-white placeholder-gray-300 rounded-2xl focus:ring-2 focus:ring-purple-500 focus:border-transparent transition-all duration-300 group-hover:bg-white/15"
              />
              <Button
                type="submit"
                size="lg"
                className="absolute right-2 top-2 h-12 w-12 bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 rounded-xl shadow-lg transition-all duration-300 hover:scale-105"
              >
                <Send className="w-5 h-5" />
              </Button>
            </div>
          </form>
          <p className="text-center text-gray-400 text-sm mt-4">
            Try: "https://example.com" or "Create a modern portfolio website"
          </p>
        </div>

        {/* Example showcase */}
        <div className="w-full max-w-6xl">
          <div className="text-center mb-8">
            <h2 className="text-3xl font-bold mb-4 bg-gradient-to-r from-white to-gray-300 bg-clip-text text-transparent">
              Websites Built with Orchids AI
            </h2>
            <p className="text-gray-400">See what's possible with AI-powered web development</p>
          </div>

          <Tabs defaultValue="portfolio" className="w-full">
            <TabsList className="grid w-full max-w-md mx-auto grid-cols-3 mb-8 bg-white/10 backdrop-blur-md">
              <TabsTrigger value="portfolio" className="data-[state=active]:bg-purple-500">
                Portfolio
              </TabsTrigger>
              <TabsTrigger value="ecommerce" className="data-[state=active]:bg-purple-500">
                E-commerce
              </TabsTrigger>
              <TabsTrigger value="landing" className="data-[state=active]:bg-purple-500">
                Landing
              </TabsTrigger>
            </TabsList>

            <TabsContent value="portfolio" className="space-y-4">
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                <ExampleCard
                  title="Developer Portfolio"
                  description="Modern portfolio with dark theme and interactive elements"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["React", "Next.js", "Tailwind"]}
                />
                <ExampleCard
                  title="Designer Showcase"
                  description="Creative portfolio with animations and smooth transitions"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["Framer", "CSS", "JavaScript"]}
                />
                <ExampleCard
                  title="Agency Website"
                  description="Professional agency site with team and services sections"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["WordPress", "PHP", "MySQL"]}
                />
              </div>
            </TabsContent>

            <TabsContent value="ecommerce" className="space-y-4">
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                <ExampleCard
                  title="Fashion Store"
                  description="Elegant e-commerce with product galleries and checkout"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["Shopify", "React", "Stripe"]}
                />
                <ExampleCard
                  title="Tech Gadgets"
                  description="Modern electronics store with reviews and comparisons"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["WooCommerce", "Vue.js", "PayPal"]}
                />
                <ExampleCard
                  title="Handmade Crafts"
                  description="Artisan marketplace with custom product options"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["Etsy API", "Node.js", "MongoDB"]}
                />
              </div>
            </TabsContent>

            <TabsContent value="landing" className="space-y-4">
              <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                <ExampleCard
                  title="SaaS Landing"
                  description="Conversion-optimized landing page with pricing tiers"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["React", "Tailwind", "Analytics"]}
                />
                <ExampleCard
                  title="App Launch"
                  description="Mobile app landing with download links and features"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["Flutter", "Firebase", "PWA"]}
                />
                <ExampleCard
                  title="Event Page"
                  description="Conference landing with registration and schedule"
                  image="/placeholder.svg?height=200&width=300"
                  tags={["Gatsby", "GraphQL", "Eventbrite"]}
                />
              </div>
            </TabsContent>
          </Tabs>
        </div>

        {/* CTA section */}
        <div className="mt-16 text-center">
          <Button
            size="lg"
            className="bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 text-white px-8 py-4 rounded-2xl text-lg font-semibold shadow-2xl hover:scale-105 transition-all duration-300"
            onClick={() => document.querySelector("input")?.focus()}
          >
            <Play className="w-5 h-5 mr-2" />
            Start Building Now
            <ArrowRight className="w-5 h-5 ml-2" />
          </Button>
        </div>
      </div>
    </div>
  )
}

// Example card component
function ExampleCard({
  title,
  description,
  image,
  tags,
}: {
  title: string
  description: string
  image: string
  tags: string[]
}) {
  return (
    <Card className="bg-white/10 backdrop-blur-md border-white/20 hover:bg-white/15 transition-all duration-300 hover:scale-105 group">
      <CardHeader className="p-0">
        <div className="relative overflow-hidden rounded-t-lg">
          <img
            src={image || "/placeholder.svg"}
            alt={title}
            className="w-full h-48 object-cover group-hover:scale-110 transition-transform duration-300"
          />
          <div className="absolute inset-0 bg-gradient-to-t from-black/50 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-300" />
        </div>
      </CardHeader>
      <CardContent className="p-6">
        <CardTitle className="text-white mb-2 text-lg">{title}</CardTitle>
        <CardDescription className="text-gray-300 mb-4">{description}</CardDescription>
        <div className="flex flex-wrap gap-2">
          {tags.map((tag) => (
            <Badge
              key={tag}
              variant="secondary"
              className="bg-purple-500/20 text-purple-200 border-purple-500/30 text-xs"
            >
              {tag}
            </Badge>
          ))}
        </div>
      </CardContent>
    </Card>
  )
}

// --- Sub-components for the three-panel layout ---

function ChatInterface({
  messages,
  onReset,
  input,
  handleInputChange,
  handleSubmit,
}: {
  messages: Message[]
  onReset: () => void
  input: string
  handleInputChange: (e: React.ChangeEvent<HTMLInputElement>) => void
  handleSubmit: (e: FormEvent<HTMLFormElement>) => void
}) {
  const messagesEndRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  return (
    <div className="h-full bg-gradient-to-b from-slate-800/90 to-slate-900/90 backdrop-blur-md border-r border-purple-500/20 flex flex-col">
      <div className="p-4 border-b border-purple-500/20 flex-shrink-0 bg-gradient-to-r from-purple-500/10 to-pink-500/10">
        <button
          onClick={onReset}
          className="flex items-center space-x-3 text-left w-full hover:opacity-80 transition-all duration-300 group"
        >
          <div className="w-10 h-10 bg-gradient-to-r from-purple-500 to-pink-500 rounded-xl flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
            <Sparkles className="w-5 h-5 text-white" />
          </div>
          <div>
            <span className="text-white font-semibold text-lg">Orchids Chat</span>
            <p className="text-gray-400 text-sm">AI-Powered Assistant</p>
          </div>
        </button>
      </div>
      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {messages.map((message) => (
            <div key={message.id} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[90%] p-4 rounded-2xl shadow-lg ${
                  message.role === "user"
                    ? "bg-gradient-to-r from-purple-500 to-pink-500 text-white"
                    : "bg-white/10 backdrop-blur-md text-gray-100 border border-white/20"
                }`}
              >
                <p className="text-sm whitespace-pre-wrap break-words leading-relaxed">{message.content}</p>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>
      <div className="p-4 border-t border-purple-500/20 flex-shrink-0 bg-gradient-to-r from-slate-800/50 to-slate-900/50 backdrop-blur-md">
        <form onSubmit={handleSubmit} className="flex space-x-3">
          <Input
            value={input}
            onChange={handleInputChange}
            placeholder="Ask Orchids to modify anything..."
            className="bg-white/10 backdrop-blur-md border-white/20 text-white placeholder-gray-400 focus:ring-2 focus:ring-purple-500 focus:border-transparent rounded-xl"
          />
          <Button
            type="submit"
            className="bg-gradient-to-r from-purple-500 to-pink-500 hover:from-purple-600 hover:to-pink-600 rounded-xl px-6 shadow-lg hover:scale-105 transition-all duration-300"
          >
            <Send className="w-4 h-4" />
          </Button>
        </form>
      </div>
    </div>
  )
}

function MainPanel({
  isLive,
  url,
  files,
  selectedFile,
  onFileSelect,
  fileContent,
}: {
  isLive: boolean
  url: string
  files: Map<string, FileNode>
  selectedFile: string
  onFileSelect: (path: string) => void
  fileContent: string
}) {
  const [activeTab, setActiveTab] = useState<"app" | "code">("app")

  return (
    <div className="flex flex-col h-full bg-gradient-to-b from-slate-800/90 to-slate-900/90 backdrop-blur-md overflow-hidden">
      <div className="flex items-center border-b border-purple-500/20 bg-gradient-to-r from-slate-800/50 to-slate-900/50 backdrop-blur-md flex-shrink-0">
        <button
          onClick={() => setActiveTab("app")}
          className={`flex items-center space-x-2 px-6 py-3 text-sm font-medium transition-all duration-300 ${
            activeTab === "app"
              ? "bg-gradient-to-r from-purple-500/20 to-pink-500/20 text-white border-b-2 border-purple-500"
              : "text-gray-400 hover:text-white hover:bg-white/5"
          }`}
        >
          <Monitor className="w-4 h-4" />
          <span>Live Preview</span>
        </button>
        <button
          onClick={() => setActiveTab("code")}
          className={`flex items-center space-x-2 px-6 py-3 text-sm font-medium transition-all duration-300 ${
            activeTab === "code"
              ? "bg-gradient-to-r from-purple-500/20 to-pink-500/20 text-white border-b-2 border-purple-500"
              : "text-gray-400 hover:text-white hover:bg-white/5"
          }`}
        >
          <Code className="w-4 h-4" />
          <span>Source Code</span>
        </button>
      </div>
      <div className="flex-1 overflow-auto">
        {activeTab === "app" && <PreviewPanel isLive={isLive} url={url} />}
        {activeTab === "code" && (
          <CodeEditorPanel
            files={files}
            selectedFile={selectedFile}
            onFileSelect={onFileSelect}
            fileContent={fileContent}
          />
        )}
      </div>
    </div>
  )
}

function CodeEditorPanel({
  files,
  selectedFile,
  onFileSelect,
  fileContent,
}: {
  files: Map<string, FileNode>
  selectedFile: string
  onFileSelect: (path: string) => void
  fileContent: string
}) {
  const [expandedFolders, setExpandedFolders] = useState<Set<string>>(new Set())

  const toggleFolder = (path: string) => {
    const newExpanded = new Set(expandedFolders)
    if (newExpanded.has(path)) newExpanded.delete(path)
    else newExpanded.add(path)
    setExpandedFolders(newExpanded)
  }

  const fileTree = Array.from(files.keys()).reduce(
    (acc, path) => {
      let currentLevel = acc
      path.split("/").forEach((part, index, arr) => {
        const isFile = index === arr.length - 1
        let existing = currentLevel.find((i) => i.name === part)
        if (!existing) {
          existing = { name: part, type: isFile ? "file" : "folder", children: isFile ? undefined : [] }
          currentLevel.push(existing)
        }
        if (!isFile) {
          currentLevel = existing.children!
        }
      })
      return acc
    },
    [] as { name: string; type: string; children?: any[] }[],
  )

  const renderFileTree = (nodes: any[], path = "") => {
    return nodes.map((node) => {
      const currentPath = path ? `${path}/${node.name}` : node.name
      const isExpanded = expandedFolders.has(currentPath)

      if (node.type === "folder") {
        return (
          <div key={currentPath}>
            <div
              className="flex items-center space-x-2 py-2 px-3 hover:bg-purple-500/10 cursor-pointer text-sm rounded-lg transition-all duration-200"
              onClick={() => toggleFolder(currentPath)}
            >
              {isExpanded ? (
                <ChevronDown className="w-4 h-4 text-purple-400" />
              ) : (
                <ChevronRight className="w-4 h-4 text-purple-400" />
              )}
              <Folder className="w-4 h-4 text-blue-400" />
              <span className="text-gray-300">{node.name}</span>
            </div>
            {isExpanded && node.children && <div className="ml-4">{renderFileTree(node.children, currentPath)}</div>}
          </div>
        )
      } else {
        return (
          <div
            key={currentPath}
            className={`flex items-center space-x-2 py-2 px-3 hover:bg-purple-500/10 cursor-pointer text-sm ml-4 rounded-lg transition-all duration-200 ${selectedFile === currentPath ? "bg-gradient-to-r from-purple-500/20 to-pink-500/20 border-l-2 border-purple-500" : ""}`}
            onClick={() => onFileSelect(currentPath)}
          >
            <File className="w-4 h-4 text-gray-400" />
            <span className="text-gray-300">{node.name}</span>
          </div>
        )
      }
    })
  }

  return (
    <div className="h-full bg-gradient-to-b from-slate-800/50 to-slate-900/50 backdrop-blur-md flex flex-col">
      <div className="p-3 border-b border-purple-500/20 text-xs text-purple-300 uppercase tracking-wide font-semibold bg-gradient-to-r from-purple-500/10 to-pink-500/10">
        <div className="flex items-center space-x-2">
          <Folder className="w-4 h-4" />
          <span>Project Explorer</span>
        </div>
      </div>
      <div className="flex-1 flex overflow-hidden">
        <ScrollArea className="w-64 border-r border-purple-500/20 bg-slate-800/30">
          <div className="p-3">{renderFileTree(fileTree)}</div>
        </ScrollArea>
        <div className="flex-1 flex flex-col">
          <div className="p-4 border-b border-purple-500/20 bg-gradient-to-r from-slate-800/50 to-slate-900/50">
            <div className="flex items-center space-x-2">
              <File className="w-4 h-4 text-purple-400" />
              <span className="text-sm text-gray-300 font-mono">{selectedFile || "Select a file"}</span>
            </div>
          </div>
          <ScrollArea className="flex-1">
            <pre className="p-6 font-mono text-sm text-gray-300 whitespace-pre-wrap leading-relaxed bg-gradient-to-b from-slate-900/30 to-slate-800/30">
              {fileContent || "// Select a file to view its contents"}
            </pre>
          </ScrollArea>
        </div>
      </div>
    </div>
  )
}

function PreviewPanel({ isLive, url }: { isLive: boolean; url: string }) {
  return (
    <div className="h-full bg-gradient-to-b from-slate-900/50 to-slate-800/50 backdrop-blur-md flex flex-col">
      <div className="flex-1 flex justify-center items-center p-6">
        <div className="h-full w-full relative">
          {isLive ? (
            <div className="relative h-full w-full">
              <iframe
                src={url}
                className="w-full h-full bg-white rounded-2xl shadow-2xl border border-purple-500/20"
                title="Live Preview"
              />
              <div className="absolute top-4 right-4">
                <Badge className="bg-green-500/20 text-green-300 border-green-500/30">
                  <div className="w-2 h-2 bg-green-400 rounded-full mr-2 animate-pulse"></div>
                  Live
                </Badge>
              </div>
            </div>
          ) : (
            <div className="flex h-full w-full items-center justify-center">
              <div className="text-center">
                <div className="w-16 h-16 bg-gradient-to-r from-purple-500 to-pink-500 rounded-2xl flex items-center justify-center mx-auto mb-4 animate-pulse">
                  <Globe className="w-8 h-8 text-white" />
                </div>
                <p className="text-gray-400 text-lg mb-2">Preparing your website...</p>
                <p className="text-gray-500 text-sm">This may take a few moments</p>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
